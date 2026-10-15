import argparse
import os
import random
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from dotenv import load_dotenv
from generate_invoice_items import build_line_items
from pymongo import MongoClient
from pymongo.errors import BulkWriteError

SOURCE = "synthetic"
ID_PREFIX = "S"
BAD_DEBT_RATE = 0.01
AMOUNT_SPREAD = (0.85, 1.15)
MIN_AMOUNT = 0.01
DUPLICATE_KEY = 11000
REPORT_EVERY = 20


@dataclass(frozen=True)
class Template:
    customer_number: str
    customer_name: str
    currency: str
    business_code: str
    payment_terms: str
    document_type: str
    post_id: int | None
    amount: float
    due_offset: int
    created_offset: int
    created1_offset: int
    baseline_offset: int
    delay: int | None


@dataclass(frozen=True)
class Pools:
    templates: list[Template]
    customer_delays: dict[str, list[int]]
    global_delays: list[int]


def _days(later, earlier):
    return (later - earlier).days


def to_template(document):
    dates = document["dates"]
    posting = dates["postingDate"]
    cleared = dates.get("clearDate")
    return Template(
        customer_number=document["customer"]["number"],
        customer_name=document["customer"]["name"],
        currency=document["currency"],
        business_code=document["businessCode"],
        payment_terms=document["paymentTerms"],
        document_type=document["documentType"],
        post_id=document.get("postingId"),
        amount=document["amounts"]["totalOpen"],
        due_offset=_days(dates["dueInDate"], posting),
        created_offset=_days(dates["documentCreateDate"], posting),
        created1_offset=_days(dates["documentCreateDate1"], posting),
        baseline_offset=_days(dates["baselineCreateDate"], posting),
        delay=None if cleared is None else _days(cleared, dates["dueInDate"]),
    )


def build_pools(documents):
    templates = [to_template(document) for document in documents]
    by_customer = defaultdict(list)
    for template in templates:
        if template.delay is not None:
            by_customer[template.customer_number].append(template.delay)
    global_delays = [template.delay for template in templates if template.delay is not None]
    return Pools(templates, dict(by_customer), global_delays)


def pick_delay(template, pools, rng):
    if template.delay is not None:
        return template.delay
    own = pools.customer_delays.get(template.customer_number)
    if own:
        return rng.choice(own)
    if pools.global_delays:
        return rng.choice(pools.global_delays)
    return 0


def invoice_key(index):
    return f"{ID_PREFIX}{index + 1:09d}"


def fabricate_invoice(index, pools, start, end, now, seed, bad_debt_rate=BAD_DEBT_RATE):
    rng = random.Random(f"{seed}:{index}")
    template = rng.choice(pools.templates)
    posting = start + timedelta(days=rng.randint(0, _days(end, start)))
    amount = max(round(template.amount * rng.uniform(*AMOUNT_SPREAD), 2), MIN_AMOUNT)
    due = posting + timedelta(days=template.due_offset)
    delay = pick_delay(template, pools, rng)
    never_paid = rng.random() < bad_debt_rate
    cleared = max(due + timedelta(days=delay), posting)
    is_open = never_paid or cleared > now
    key = invoice_key(index)
    return {
        "_id": key,
        "invoiceId": key,
        "docId": key,
        "businessCode": template.business_code,
        "customer": {
            "number": template.customer_number,
            "name": template.customer_name,
            "nameLower": template.customer_name.lower(),
        },
        "currency": template.currency,
        "documentType": template.document_type,
        "postingId": template.post_id,
        "isOpen": is_open,
        "amounts": {"totalOpen": amount},
        "dates": {
            "postingDate": posting,
            "documentCreateDate": posting + timedelta(days=template.created_offset),
            "documentCreateDate1": posting + timedelta(days=template.created1_offset),
            "dueInDate": due,
            "baselineCreateDate": posting + timedelta(days=template.baseline_offset),
            "clearDate": None if is_open else cleared,
        },
        "paymentTerms": template.payment_terms,
        "businessYear": posting.year,
        "lines": build_line_items(amount, rng),
        "source": SOURCE,
        "updatedAt": now,
    }


def load_pools(collection):
    projection = {
        "customer": 1, "currency": 1, "businessCode": 1, "paymentTerms": 1,
        "documentType": 1, "postingId": 1, "amounts.totalOpen": 1, "dates": 1,
    }
    documents = list(collection.find({"source": {"$exists": False}}, projection))
    last_posting = max(document["dates"]["postingDate"] for document in documents)
    return build_pools(documents), last_posting


def existing_ids(collection, ids):
    return {document["_id"] for document in collection.find({"_id": {"$in": ids}}, {"_id": 1})}


def insert_missing(collection, documents):
    if not documents:
        return 0
    try:
        result = collection.insert_many(documents, ordered=False)
    except BulkWriteError as error:
        codes = {failure["code"] for failure in error.details["writeErrors"]}
        if codes != {DUPLICATE_KEY}:
            raise
        return error.details["nInserted"]
    return len(result.inserted_ids)


def run(collection, pools, count, seed, batch_size, start, end, now, report=None):
    inserted = skipped = 0
    for batch, first in enumerate(range(0, count, batch_size), start=1):
        indexes = range(first, min(first + batch_size, count))
        present = existing_ids(collection, [invoice_key(index) for index in indexes])
        documents = [
            fabricate_invoice(index, pools, start, end, now, seed)
            for index in indexes
            if invoice_key(index) not in present
        ]
        written = insert_missing(collection, documents)
        inserted += written
        skipped += len(indexes) - written
        if report and batch % REPORT_EVERY == 0:
            report(first + len(indexes), inserted, skipped)
    return {"inserted": inserted, "skipped": skipped}


def purge(collection):
    return collection.delete_many({"source": SOURCE}).deleted_count


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description="Insert synthetic invoices modelled on the real ones.")
    parser.add_argument("--uri", default=os.environ.get("MONGO_URI", "mongodb://localhost:27017"))
    parser.add_argument("--db", default=os.environ.get("MONGO_DB_NAME", "invoices_db"))
    parser.add_argument("--count", type=int, default=1_000_000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--batch-size", type=int, default=5_000)
    parser.add_argument("--purge", action="store_true", help="delete every synthetic invoice and exit")
    args = parser.parse_args()

    collection = MongoClient(args.uri)[args.db]["invoices"]
    if args.purge:
        print(f"Deleted {purge(collection)} synthetic invoices")
        return

    pools, last_posting = load_pools(collection)
    now = datetime.now(UTC).replace(tzinfo=None)
    start = last_posting + timedelta(days=1)
    end = datetime(now.year, now.month, now.day)
    started = time.perf_counter()

    def report(done, inserted, skipped):
        rate = done / (time.perf_counter() - started)
        print(f"{done:>9}/{args.count}  inserted {inserted}  skipped {skipped}  {rate:,.0f} invoices/s", flush=True)

    stats = run(collection, pools, args.count, args.seed, args.batch_size, start, end, now, report)
    elapsed = time.perf_counter() - started
    total = collection.count_documents({"source": SOURCE})
    open_share = collection.count_documents({"source": SOURCE, "isOpen": True}) / max(total, 1)
    print(f"Inserted {stats['inserted']}, skipped {stats['skipped']} in {elapsed:.0f} s")
    print(f"Synthetic invoices now: {total}, {open_share:.1%} open, posted {start.date()} to {end.date()}")


if __name__ == "__main__":
    main()
