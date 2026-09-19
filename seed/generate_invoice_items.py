"""Generate synthetic line items for each invoice so they sum exactly to
that invoice's total_open_amount, embed them in the invoice as `lines`, and
load products into MongoDB. Run it after load_to_mongo.py.

Lines are embedded rather than kept in their own collection: an invoice has
at most 5 of them, they never change after the invoice is issued, and the
product/brand/category analytics would otherwise join every invoice to its
lines (measured at ~1.4 s for the whole data set).

Approach: for each invoice, pick a handful of products (tier mix chosen by
invoice size, so a $600k invoice isn't "500,000x thermal paste"), assign
plausible bulk quantities, then scale catalog list prices so the line
items reconcile to the cent. The scale factor stands in for per-contract
negotiated pricing, which is normal in B2B distribution - it's kept close
to 1x by retrying compositions, not applied as a blind multiplier.
"""

import argparse
import math
import random

import pandas as pd
from pymongo import MongoClient, UpdateOne

from indexes import PRODUCT_INDEXES, sync_indexes
from products import PRODUCTS, TIER_QTY_RANGE

SIZE_BRACKETS = [
    # (max_total, k_range, tiers)
    (50, (1, 1), ["accessory"]),
    (500, (1, 2), ["accessory", "component"]),
    (3000, (1, 3), ["component", "gpu_consumer"]),
    (20000, (2, 4), ["gpu_consumer", "component", "enterprise"]),
    (float("inf"), (2, 5), ["enterprise", "gpu_consumer"]),
]

MAX_ATTEMPTS = 10
ACCEPTABLE_LOG_SCALE = math.log(1.8)  # prefer scale factors within ~0.55x-1.8x


def pick_composition(target: float, rng: random.Random):
    for max_total, k_range, tiers in SIZE_BRACKETS:
        if target <= max_total:
            break

    candidates = [p for p in PRODUCTS if p["tier"] in tiers]
    best = None
    for _ in range(MAX_ATTEMPTS):
        k = rng.randint(*k_range)
        k = min(k, len(candidates))
        picks = rng.sample(candidates, k)
        items = []
        raw_total = 0.0
        for product in picks:
            lo, hi = TIER_QTY_RANGE[product["tier"]]
            qty = rng.randint(lo, hi)
            items.append({"product": product, "quantity": qty})
            raw_total += product["listPrice"] * qty

        scale = target / raw_total if raw_total else 1.0
        score = abs(math.log(scale)) if scale > 0 else float("inf")
        if best is None or score < best[0]:
            best = (score, items, scale)
        if score <= ACCEPTABLE_LOG_SCALE:
            break

    return best[1], best[2]


def build_line_items(target: float, rng: random.Random):
    items, scale = pick_composition(target, rng)

    lines = []
    running_total = 0.0
    for i, entry in enumerate(items, start=1):
        product = entry["product"]
        qty = entry["quantity"]
        unit_price = round(product["listPrice"] * scale, 2)
        is_last = i == len(items)
        if is_last:
            line_total = round(target - running_total, 2)
        else:
            line_total = round(unit_price * qty, 2)
        running_total += line_total

        lines.append({
            "lineNo": i,
            "sku": product["sku"],
            "productName": product["name"],
            "brand": product["brand"],
            "category": product["category"],
            "quantity": qty,
            "unitPrice": unit_price,
            "lineTotal": line_total,
        })

    return lines


def load_invoices(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    df["invoice_id"] = df["invoice_id"].astype("Int64")
    df["doc_id"] = df["doc_id"].astype("Int64")
    df["invoiceKey"] = df["invoice_id"].fillna(df["doc_id"]).astype(str)
    # matches the upsert semantics of load_to_mongo.py: last row for a
    # given key wins
    return df.drop_duplicates(subset="invoiceKey", keep="last")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", default="seed/dataset.csv")
    parser.add_argument("--uri", default="mongodb://localhost:27017")
    parser.add_argument("--db", default="invoices_db")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--batch-size", type=int, default=2000)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    df = load_invoices(args.csv)

    client = MongoClient(args.uri)
    db = client[args.db]

    products_col = db["products"]
    sync_indexes(products_col, PRODUCT_INDEXES)
    product_ops = [UpdateOne({"_id": p["sku"]}, {"$set": {**p, "_id": p["sku"]}}, upsert=True) for p in PRODUCTS]
    products_col.bulk_write(product_ops, ordered=False)
    print(f"Upserted {len(PRODUCTS)} products")

    invoices_col = db["invoices"]
    ops = []
    matched = 0
    total_lines = 0
    max_abs_diff = 0.0
    for _, row in df.iterrows():
        target = round(float(row["total_open_amount"]), 2)
        lines = build_line_items(target, rng)

        reconciled = round(sum(l["lineTotal"] for l in lines), 2)
        max_abs_diff = max(max_abs_diff, abs(reconciled - target))

        ops.append(UpdateOne({"_id": row["invoiceKey"]}, {"$set": {"lines": lines}}))
        total_lines += len(lines)

        if len(ops) >= args.batch_size:
            matched += invoices_col.bulk_write(ops, ordered=False).matched_count
            ops = []
    if ops:
        matched += invoices_col.bulk_write(ops, ordered=False).matched_count

    print(f"Embedded {total_lines} line items in {matched} of {len(df)} invoices")
    print(f"Max |reconciled - target| across all invoices: {max_abs_diff}")


if __name__ == "__main__":
    main()
