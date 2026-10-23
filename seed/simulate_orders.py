import argparse
import os
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from fabricate_orders import SOURCE, fabricate_invoice, insert_missing, load_pools
from pymongo import MongoClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from app.invoices.events import Actor, ActorType, EventType, build_event, record_event  # noqa: E402
from app.invoices.service import close_invoice  # noqa: E402
from app.utils.dates import today_in_business_timezone  # noqa: E402

BANK_IMPORT = Actor(ActorType.SYSTEM, "bank-import")
PAYABLE_WINDOW = timedelta(days=90)


def new_order(pools, now, n):
    second = f"{now:%y%m%d%H%M%S}"
    today = datetime.combine(now.date(), datetime.min.time())
    order = fabricate_invoice(n, pools, today, today, now, seed=second)
    key = f"L{second}{n:02d}"
    order.update({"_id": key, "invoiceId": key, "docId": key, "isOpen": True})
    order["dates"]["clearDate"] = None
    return order


def add_orders(invoices, pools, now, count):
    return insert_missing(invoices, [new_order(pools, now, n) for n in range(count)])


def pick_payable(invoices, now, count):
    pipeline = [
        {"$match": {
            "source": SOURCE,
            "isOpen": True,
            "dates.dueInDate": {"$gte": now - PAYABLE_WINDOW, "$lte": now},
        }},
        {"$sample": {"size": count}},
        {"$project": {"_id": 1}},
    ]
    return [invoice["_id"] for invoice in invoices.aggregate(pipeline)]


def settle(client, db, invoice_id):
    paid_on = today_in_business_timezone()

    def close_and_record(session):
        if not close_invoice(db["invoices"], invoice_id, paid_on, session=session):
            return False
        event = build_event(invoice_id, EventType.CLOSED, BANK_IMPORT, datetime.now(UTC), paid_on=paid_on)
        record_event(db["invoice_events"], event, session=session)
        return True

    with client.start_session() as session:
        return session.with_transaction(close_and_record)


def tick(client, db, pools, orders, payments):
    now = datetime.now(UTC).replace(tzinfo=None)
    added = add_orders(db["invoices"], pools, now, orders)
    paid = sum(settle(client, db, invoice_id) for invoice_id in pick_payable(db["invoices"], now, payments))
    print(f"{now:%H:%M:%S}  +{added} orders, {paid} paid", flush=True)


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description="Simulate the ERP: add new orders and settle open invoices.")
    parser.add_argument("--uri", default=os.environ.get("MONGO_URI", "mongodb://localhost:27017"))
    parser.add_argument("--db", default=os.environ.get("MONGO_DB_NAME", "invoices_db"))
    parser.add_argument("--orders", type=int, default=5, help="new orders per tick")
    parser.add_argument("--payments", type=int, default=3, help="invoices settled per tick")
    parser.add_argument("--every", type=int, default=60, help="seconds between ticks")
    parser.add_argument("--once", action="store_true", help="run a single tick and exit")
    args = parser.parse_args()

    client = MongoClient(args.uri)
    db = client[args.db]
    pools = load_pools(db["invoices"])
    try:
        while True:
            tick(client, db, pools, args.orders, args.payments)
            if args.once:
                return
            time.sleep(args.every)
    except KeyboardInterrupt:
        print("Stopped")


if __name__ == "__main__":
    main()
