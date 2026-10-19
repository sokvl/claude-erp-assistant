from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import uuid4

from pymongo import ReturnDocument

from app.invoices.events import to_midnight
from app.limits import PENDING_ACTION_TTL_MINUTES, QUERY_TIMEOUT_MS

PENDING_ACTIONS_COLLECTION = "pending_actions"

CLOSE_INVOICE_ACTION = "close_invoice"


@dataclass(frozen=True)
class PendingAction:
    action_id: str
    invoice_id: str
    consequence: dict[str, Any]


def save_pending_action(
    collection: Any,
    conversation_id: str | None,
    requested_by: str | None,
    invoice_id: str,
    reason: str,
    consequence: dict[str, Any],
) -> str:
    created_at = datetime.now(UTC)
    document = {
        "_id": uuid4().hex,
        "action": CLOSE_INVOICE_ACTION,
        "invoiceId": invoice_id,
        "reason": reason,
        "consequence": consequence,
        "status": "pending",
        "conversationId": conversation_id,
        "requestedBy": requested_by,
        "createdAt": created_at,
        "expiresAt": created_at + timedelta(minutes=PENDING_ACTION_TTL_MINUTES),
        "decidedAt": None,
        "decidedBy": None,
        "decidedReason": None,
    }
    collection.insert_one(document)
    return document["_id"]


def build_decidable_filter(action_id: str, decided_by: str, now: datetime) -> dict[str, Any]:
    return {"_id": action_id, "requestedBy": decided_by, "status": "pending", "expiresAt": {"$gt": now}}


def find_decidable_action(collection: Any, action_id: str, decided_by: str) -> dict[str, Any] | None:
    return collection.find_one(build_decidable_filter(action_id, decided_by, datetime.now(UTC)), max_time_ms=QUERY_TIMEOUT_MS)


def decide_pending_action(
    collection: Any,
    action_id: str,
    decided_by: str,
    approve: bool,
    decided_reason: str | None,
    paid_on: date | None = None,
    session: Any = None,
) -> dict[str, Any] | None:
    now = datetime.now(UTC)
    return collection.find_one_and_update(
        build_decidable_filter(action_id, decided_by, now),
        {
            "$set": {
                "status": "approved" if approve else "rejected",
                "decidedAt": now,
                "decidedBy": decided_by,
                "decidedReason": decided_reason,
                "paidOn": to_midnight(paid_on),
            }
        },
        return_document=ReturnDocument.AFTER,
        maxTimeMS=QUERY_TIMEOUT_MS,
        session=session,
    )


def record_outcome(collection: Any, action_id: str, invoice_closed: bool, session: Any = None) -> None:
    collection.update_one({"_id": action_id}, {"$set": {"invoiceClosed": invoice_closed}}, session=session)
