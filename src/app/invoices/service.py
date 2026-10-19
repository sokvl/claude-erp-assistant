from datetime import UTC, date, datetime
from typing import Any

from app.invoices.events import Actor, ActorType, EventType, build_event, record_event, to_midnight
from app.invoices.pending_actions import save_pending_action
from app.invoices.query import (
    INVOICE_PROJECTION,
    build_analytics_pipeline,
    build_invoice_filter,
    build_list_query,
)
from app.invoices.schemas import InvoiceAnalyticsParams, InvoiceListParams
from app.limits import QUERY_TIMEOUT_MS
from app.utils.dates import today_in_business_timezone


def list_invoices(collection: Any, params: InvoiceListParams) -> dict[str, Any]:
    search_criteria = build_invoice_filter(params, params.as_of or today_in_business_timezone())
    query = build_list_query(
        criteria=search_criteria,
        sort_by=params.sort_by,
        order=params.sort_order,
        page=params.page,
        page_size=params.page_size,
    )
    return {
        "page": params.page,
        "pageSize": params.page_size,
        "total": collection.count_documents(query["filter"], maxTimeMS=QUERY_TIMEOUT_MS),
        "items": list(collection.find(**query, max_time_ms=QUERY_TIMEOUT_MS)),
    }


def analyze_invoices(collection: Any, params: InvoiceAnalyticsParams) -> dict[str, Any]:
    as_of = params.as_of or today_in_business_timezone()
    invoice_filter = build_invoice_filter(params, as_of)
    pipeline = build_analytics_pipeline(
        criteria=invoice_filter,
        group_by=params.group_by,
        as_of=as_of,
        limit=params.limit,
    )
    return {
        "asOf": as_of.isoformat(),
        "groupBy": params.group_by,
        "filters": params.model_dump(mode="json", exclude_none=True, exclude={"as_of", "group_by", "limit"}),
        "coverage": _coverage(collection),
        "currencies": list(collection.aggregate(pipeline, maxTimeMS=QUERY_TIMEOUT_MS)),
    }


def request_close(
    invoices: Any,
    pending_actions: Any,
    events: Any,
    invoice_id: str,
    reason: str,
    suggested_paid_on: date | None,
    conversation_id: str | None,
    requested_by: str | None,
) -> dict[str, Any]:
    invoice = invoices.find_one({"_id": invoice_id}, INVOICE_PROJECTION, max_time_ms=QUERY_TIMEOUT_MS)
    if invoice is None:
        raise ValueError(f"No invoice {invoice_id!r} found")
    if not invoice["isOpen"]:
        raise ValueError(f"Invoice {invoice_id!r} is not open; nothing to close")
    posting_date = invoice["dates"]["postingDate"].date()
    problem = check_paid_on(suggested_paid_on, posting_date, today_in_business_timezone())
    if problem:
        raise ValueError(problem)
    consequence = {
        "currentAmountOpen": invoice["amounts"]["totalOpen"],
        "currency": invoice["currency"],
        "customerNumber": invoice["customer"]["number"],
        "customerName": invoice["customer"]["name"],
        "postingDate": posting_date.isoformat(),
        "suggestedPaidOn": suggested_paid_on.isoformat() if suggested_paid_on else None,
    }
    action_id = save_pending_action(
        pending_actions, conversation_id, requested_by, invoice_id, reason, consequence, suggested_paid_on
    )
    record_event(
        events,
        build_event(
            invoice_id,
            EventType.CLOSE_REQUESTED,
            Actor(ActorType.USER, requested_by or "unknown"),
            datetime.now(UTC),
            reason=reason,
            suggested_paid_on=suggested_paid_on,
            action_id=action_id,
            conversation_id=conversation_id,
        ),
    )
    return {
        "status": "awaiting_approval",
        "pendingActionId": action_id,
        "invoiceId": invoice_id,
        "consequence": consequence,
    }


def close_invoice(collection: Any, invoice_id: str, paid_on: date | None, session: Any = None) -> bool:
    now = datetime.now(UTC)
    result = collection.update_one(
        {"_id": invoice_id, "isOpen": True},
        {"$set": {"isOpen": False, "closedAt": now, "updatedAt": now, "dates.clearDate": to_midnight(paid_on)}},
        session=session,
    )
    return result.modified_count > 0


def read_posting_date(collection: Any, invoice_id: str) -> date | None:
    invoice = collection.find_one({"_id": invoice_id}, {"_id": 0, "dates.postingDate": 1}, max_time_ms=QUERY_TIMEOUT_MS)
    return invoice["dates"]["postingDate"].date() if invoice else None


def check_paid_on(paid_on: date | None, posting_date: date | None, today: date) -> str | None:
    if paid_on is None:
        return None
    if paid_on > today:
        return f"The payment date {paid_on} is in the future"
    if posting_date is not None and paid_on < posting_date:
        return f"The payment date {paid_on} is before the invoice was posted on {posting_date}"
    return None


def _coverage(collection: Any) -> dict[str, str | None]:
    return {
        "firstPostingDate": _edge_posting_date(collection, 1),
        "lastPostingDate": _edge_posting_date(collection, -1),
    }


def _edge_posting_date(collection: Any, direction: int) -> str | None:
    document = collection.find_one(
        {},
        {"_id": 0, "dates.postingDate": 1},
        sort=[("dates.postingDate", direction)],
        max_time_ms=QUERY_TIMEOUT_MS,
    )
    return document["dates"]["postingDate"].date().isoformat() if document else None
