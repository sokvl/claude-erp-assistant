import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv
from indexes import INVOICE_EVENT_INDEXES, PENDING_ACTION_INDEXES, sync_indexes
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from app.invoices.events import Actor, ActorType, EventType, build_event  # noqa: E402

UNKNOWN = "unknown"


def as_utc(moment):
    return moment.replace(tzinfo=UTC) if moment is not None and moment.tzinfo is None else moment


def as_day(moment):
    return moment.date() if moment is not None else None


def plan_events(action):
    requested_by = Actor(ActorType.USER, action.get("requestedBy") or UNKNOWN)
    decided_by = Actor(ActorType.USER, action.get("decidedBy") or UNKNOWN)
    common = {
        "action_id": action["_id"],
        "conversation_id": action.get("conversationId"),
        "suggested_paid_on": as_day(action.get("suggestedPaidOn")),
    }
    events = [
        build_event(action["invoiceId"], EventType.CLOSE_REQUESTED, requested_by, as_utc(action["createdAt"]),
                    reason=action.get("reason"), **common)
    ]
    if action["status"] == "approved" and action.get("invoiceClosed"):
        events.append(build_event(action["invoiceId"], EventType.CLOSED, decided_by, as_utc(action["decidedAt"]),
                                  reason=action.get("reason"), paid_on=as_day(action.get("paidOn")), **common))
    if action["status"] == "rejected":
        events.append(build_event(action["invoiceId"], EventType.CLOSE_REJECTED, decided_by, as_utc(action["decidedAt"]),
                                  reason=action.get("decidedReason"), **common))
    return events


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description="Write the event log for closes made before it existed.")
    parser.add_argument("--uri", default=os.environ.get("MONGO_URI", "mongodb://localhost:27017"))
    parser.add_argument("--db", default=os.environ.get("MONGO_DB_NAME", "invoices_db"))
    parser.add_argument("--apply", action="store_true", help="write the changes; without it only print the plan")
    args = parser.parse_args()

    db = MongoClient(args.uri)[args.db]
    actions = list(db["pending_actions"].find({"action": "close_invoice"}).sort("createdAt", 1))
    planned = [event for action in actions for event in plan_events(action)]
    with_reason = list(db["invoices"].find({"closedReason": {"$exists": True}}, {"_id": 1}))

    for event in planned:
        print(f"event   {event['invoiceId']:<12} {event['type']:<16} by {event['actor']['id']:<8} at {event['at']:%Y-%m-%d %H:%M}")
    for invoice in with_reason:
        print(f"unset   {invoice['_id']:<12} closedReason, new updatedAt")
    print("index   invoice_events (invoiceId, at, _id) and unique (actionId, type); then the TTL on pending_actions")
    if not args.apply:
        print("dry run: nothing written; rerun with --apply")
        return

    sync_indexes(db["invoice_events"], INVOICE_EVENT_INDEXES)
    written = skipped = 0
    for event in planned:
        try:
            db["invoice_events"].insert_one(event)
            written += 1
        except DuplicateKeyError:
            skipped += 1
    now = datetime.now(UTC)
    unset = db["invoices"].update_many({"closedReason": {"$exists": True}}, {"$unset": {"closedReason": ""}, "$set": {"updatedAt": now}})
    sync_indexes(db["pending_actions"], PENDING_ACTION_INDEXES)
    print(f"events written {written}, already there {skipped}; closedReason removed from {unset.modified_count} invoices; indexes synced")


if __name__ == "__main__":
    main()
