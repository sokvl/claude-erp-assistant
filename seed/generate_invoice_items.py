"""Generate synthetic line items for each invoice so they sum exactly to
that invoice's total_open_amount, and load products + invoice_items into
MongoDB.

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
from pymongo import ASCENDING, MongoClient, UpdateOne

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


def build_line_items(invoice_id: str, target: float, rng: random.Random):
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
            "_id": f"{invoice_id}-{i}",
            "invoiceId": invoice_id,
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


def ensure_product_indexes(collection):
    """Indexes supporting spec search (app/catalog/query.py).

    At 52 documents these cannot measurably help - the whole collection is a
    single storage page, where a COLLSCAN beats IXSCAN+FETCH. They encode
    query intent and are already correct if the catalog grows.

    The spec indexes are partial because 41 of 52 products have no `specs` at
    all, so this keeps them at 11 entries instead of 52 with 41 nulls.
    """
    # (category, listPrice) makes a standalone category index redundant by the
    # index-prefix rule, so it replaces rather than supplements it.
    collection.create_index([("category", ASCENDING), ("listPrice", ASCENDING)], name="category_listPrice")
    collection.create_index([("brand", ASCENDING)], name="brand")
    collection.create_index(
        [("specs.vramGb", ASCENDING), ("specs.fp16TensorTflopsDense", ASCENDING)],
        name="specs_vram_fp16",
        partialFilterExpression={"specs": {"$exists": True}},
    )
    collection.create_index(
        [("specs.useCases", ASCENDING)],
        name="specs_useCases",
        partialFilterExpression={"specs": {"$exists": True}},
    )


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
    ensure_product_indexes(products_col)
    product_ops = [UpdateOne({"_id": p["sku"]}, {"$set": {**p, "_id": p["sku"]}}, upsert=True) for p in PRODUCTS]
    products_col.bulk_write(product_ops, ordered=False)
    print(f"Upserted {len(PRODUCTS)} products")

    items_col = db["invoice_items"]
    items_col.create_index([("invoiceId", ASCENDING)])

    ops = []
    total_lines = 0
    max_abs_diff = 0.0
    for _, row in df.iterrows():
        invoice_id = row["invoiceKey"]
        target = round(float(row["total_open_amount"]), 2)
        lines = build_line_items(invoice_id, target, rng)

        reconciled = round(sum(l["lineTotal"] for l in lines), 2)
        max_abs_diff = max(max_abs_diff, abs(reconciled - target))

        for line in lines:
            ops.append(UpdateOne({"_id": line["_id"]}, {"$set": line}, upsert=True))
        total_lines += len(lines)

        if len(ops) >= args.batch_size:
            items_col.bulk_write(ops, ordered=False)
            ops = []
    if ops:
        items_col.bulk_write(ops, ordered=False)

    print(f"Upserted {total_lines} line items across {len(df)} invoices")
    print(f"Max |reconciled - target| across all invoices: {max_abs_diff}")


if __name__ == "__main__":
    main()
