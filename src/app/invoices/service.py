from datetime import date
from typing import Any

from app.invoices.query import build_analytics_pipeline, build_invoice_filter, build_list_pipeline
from app.invoices.schemas import InvoiceAnalyticsParams, InvoiceListParams
from app.limits import QUERY_TIMEOUT_MS


def list_invoices(collection: Any, params: InvoiceListParams) -> dict[str, Any]:
    pipeline = build_list_pipeline(
        criteria=build_invoice_filter(params, params.as_of or date.today()),
        sort_by=params.sort_by,
        order=params.sort_order,
        page=params.page,
        page_size=params.page_size,
    )
    result = next(iter(collection.aggregate(pipeline, maxTimeMS=QUERY_TIMEOUT_MS)), None) or {"items": [], "total": 0}
    return {
        "page": params.page,
        "pageSize": params.page_size,
        "total": result["total"],
        "items": result["items"],
    }


def analyze_invoices(collection: Any, params: InvoiceAnalyticsParams) -> dict[str, Any]:
    as_of = params.as_of or date.today()
    pipeline = build_analytics_pipeline(
        criteria=build_invoice_filter(params, as_of),
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
