from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from enum import StrEnum
from typing import Any
from uuid import uuid4

from app.limits import MAX_INVOICE_EVENTS, QUERY_TIMEOUT_MS

INVOICE_EVENTS_COLLECTION = "invoice_events"
HISTORY_SORT = [("at", 1), ("_id", 1)]


class EventType(StrEnum):
    CLOSE_REQUESTED = "close_requested"
    CLOSED = "closed"
    CLOSE_REJECTED = "close_rejected"


class ActorType(StrEnum):
    USER = "user"
    SYSTEM = "system"


@dataclass(frozen=True)
class Actor:
    type: ActorType
    id: str


def build_event(
    invoice_id: str,
    event_type: EventType,
    actor: Actor,
    at: datetime,
    reason: str | None = None,
    paid_on: date | None = None,
    suggested_paid_on: date | None = None,
    action_id: str | None = None,
    conversation_id: str | None = None,
) -> dict[str, Any]:
    return {
        "_id": uuid4().hex,
        "invoiceId": invoice_id,
        "type": event_type.value,
        "at": at,
        "actor": {"type": actor.type.value, "id": actor.id},
        "reason": reason,
        "paidOn": to_midnight(paid_on),
        "suggestedPaidOn": to_midnight(suggested_paid_on),
        "actionId": action_id,
        "conversationId": conversation_id,
    }


def to_midnight(day: date | None) -> datetime | None:
    return None if day is None else datetime.combine(day, time.min, tzinfo=UTC)


def record_event(collection: Any, event: dict[str, Any], session: Any = None) -> str:
    collection.insert_one(event, session=session)
    return event["_id"]


def build_history_filter(invoice_id: str) -> dict[str, Any]:
    return {"invoiceId": invoice_id}


def list_events(collection: Any, invoice_id: str) -> list[dict[str, Any]]:
    cursor = collection.find(
        build_history_filter(invoice_id), sort=HISTORY_SORT, limit=MAX_INVOICE_EVENTS, max_time_ms=QUERY_TIMEOUT_MS
    )
    return list(cursor)
