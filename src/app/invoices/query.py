import re
from datetime import date, datetime, time
from typing import Any

from app.catalog.enums import SortOrder
from app.invoices.enums import LINE_ITEM_FIELDS, PERIOD_UNITS, SORT_PATHS, GroupBy, InvoiceSortField, InvoiceStatus
from app.invoices.schemas import InvoiceFilter
from app.limits import DEFAULT_ANALYTICS_ROWS, MAX_ANALYTICS_ROWS

INVOICE_PROJECTION = {
    "_id": 0,
    "invoiceId": 1,
    "customer.number": 1,
    "customer.name": 1,
    "currency": 1,
    "amounts.totalOpen": 1,
    "isOpen": 1,
    "dates.postingDate": 1,
    "dates.dueInDate": 1,
    "dates.clearDate": 1,
}

MONEY_FIELDS = ("totalAmount", "averageAmount", "openAmount", "overdueAmount")


def _range(minimum: Any, maximum: Any) -> dict[str, Any]:
    bounds: dict[str, Any] = {}
    if minimum is not None:
        bounds["$gte"] = minimum
    if maximum is not None:
        bounds["$lte"] = maximum
    return bounds


def _start_of(day: date) -> datetime:
    return datetime.combine(day, time.min)


def build_invoice_filter(filters: InvoiceFilter, as_of: date) -> dict[str, Any]:
    criteria: dict[str, Any] = {}

    posted = _range(
        None if filters.posted_from is None else _start_of(filters.posted_from),
        None if filters.posted_to is None else datetime.combine(filters.posted_to, time.max),
    )
    if posted:
        criteria["dates.postingDate"] = posted

    if filters.customer:
        criteria["$or"] = [
            {"customer.number": filters.customer},
            {"customer.nameLower": {"$regex": "^" + re.escape(filters.customer.lower())}},
        ]
    if filters.currency:
        criteria["currency"] = filters.currency

    if filters.status == InvoiceStatus.OPEN:
        criteria["isOpen"] = True
    elif filters.status == InvoiceStatus.CLEARED:
        criteria["isOpen"] = False
    elif filters.status == InvoiceStatus.OVERDUE:
        criteria["isOpen"] = True
        criteria["dates.dueInDate"] = {"$lt": _start_of(as_of)}

    amount = _range(filters.min_amount, filters.max_amount)
    if amount:
        criteria["amounts.totalOpen"] = amount

    return criteria


def build_list_query(
    *,
    criteria: dict[str, Any],
    sort_by: InvoiceSortField,
    order: SortOrder,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    if not isinstance(sort_by, InvoiceSortField):
        raise ValueError(f"sort_by must be an InvoiceSortField, got {sort_by!r}")
    if not isinstance(order, SortOrder):
        raise ValueError(f"order must be a SortOrder, got {order!r}")

    direction = 1 if order is SortOrder.ASC else -1
    return {
        "filter": criteria,
        "projection": INVOICE_PROJECTION,
        "sort": [(SORT_PATHS[sort_by], direction), ("_id", direction)],
        "skip": (page - 1) * page_size,
        "limit": page_size,
    }


def _invoice_facts(group_by: GroupBy | None) -> list[dict[str, Any]]:
    if group_by is None:
        key: Any = {"$literal": None}
    elif group_by is GroupBy.CUSTOMER:
        key = "$customer.number"
    else:
        truncated = {"$dateTrunc": {"date": "$dates.postingDate", "unit": PERIOD_UNITS[group_by]}}
        key = {"$dateToString": {"format": "%Y-%m-%d", "date": truncated}}
    return [
        {
            "$project": {
                "key": key,
                "label": "$customer.name",
                "currency": 1,
                "amount": "$amounts.totalOpen",
                "isOpen": 1,
                "postingDate": "$dates.postingDate",
                "dueInDate": "$dates.dueInDate",
                "clearDate": "$dates.clearDate",
            }
        }
    ]


def _line_item_facts(group_by: GroupBy) -> list[dict[str, Any]]:
    field = LINE_ITEM_FIELDS[group_by]
    return [
        {"$unwind": "$lines"},
        {
            "$group": {
                "_id": {"key": f"$lines.{field}", "invoice": "$_id"},
                "label": {"$first": "$lines.productName"},
                "currency": {"$first": "$currency"},
                "amount": {"$sum": "$lines.lineTotal"},
                "units": {"$sum": "$lines.quantity"},
                "isOpen": {"$first": "$isOpen"},
                "postingDate": {"$first": "$dates.postingDate"},
                "dueInDate": {"$first": "$dates.dueInDate"},
                "clearDate": {"$first": "$dates.clearDate"},
            }
        },
        {"$set": {"key": "$_id.key"}},
    ]


def build_analytics_pipeline(
    *,
    criteria: dict[str, Any],
    group_by: GroupBy | None,
    as_of: date,
    limit: int | None,
) -> list[dict[str, Any]]:
    if group_by is not None and not isinstance(group_by, GroupBy):
        raise ValueError(f"group_by must be a GroupBy, got {group_by!r}")

    line_grain = group_by in LINE_ITEM_FIELDS
    labelled = group_by in (GroupBy.CUSTOMER, GroupBy.PRODUCT)
    cutoff = _start_of(as_of)

    kpis: dict[str, Any] = {
        "invoiceCount": {"$sum": 1},
        "totalAmount": {"$sum": "$amount"},
        "averageAmount": {"$avg": "$amount"},
        "openAmount": {"$sum": {"$cond": ["$isOpen", "$amount", 0]}},
        "overdueAmount": {
            "$sum": {"$cond": [{"$and": ["$isOpen", {"$lt": ["$dueInDate", cutoff]}]}, "$amount", 0]}
        },
        "averageDaysToPay": {
            "$avg": {
                "$cond": [
                    "$isOpen",
                    None,
                    {"$dateDiff": {"startDate": "$postingDate", "endDate": "$clearDate", "unit": "day"}},
                ]
            }
        },
    }
    rounded: dict[str, Any] = {field: {"$round": [f"${field}", 2]} for field in MONEY_FIELDS}
    rounded["averageDaysToPay"] = {"$round": ["$averageDaysToPay", 1]}
    row: dict[str, Any] = {} if group_by is None else {"key": "$_id.key"}

    if labelled:
        kpis["label"] = {"$max": "$label"}
        row["label"] = "$label"
    row |= {field: f"${field}" for field in ("invoiceCount", *MONEY_FIELDS, "averageDaysToPay")}
    if line_grain:
        kpis["units"] = {"$sum": "$units"}
        row["units"] = "$units"
    if group_by is GroupBy.PRODUCT:
        rounded["averageUnitPrice"] = {"$round": [{"$divide": ["$totalAmount", "$units"]}, 2]}
        row["averageUnitPrice"] = "$averageUnitPrice"

    if group_by in PERIOD_UNITS:
        sort_by: dict[str, int] = {"_id.key": 1}
        rows = limit or MAX_ANALYTICS_ROWS
    else:
        sort_by = {"totalAmount": -1, "_id.key": 1}
        rows = limit or DEFAULT_ANALYTICS_ROWS

    return [
        {"$match": criteria},
        *(_line_item_facts(group_by) if line_grain else _invoice_facts(group_by)),
        {"$group": {"_id": {"key": "$key", "currency": "$currency"}, **kpis}},
        {"$set": rounded},
        {
            "$group": {
                "_id": "$_id.currency",
                "groupCount": {"$sum": 1},
                "rows": {"$topN": {"n": rows, "sortBy": sort_by, "output": row}},
            }
        },
        {"$sort": {"_id": 1}},
        {"$project": {"_id": 0, "currency": "$_id", "groupCount": "$groupCount", "rows": "$rows"}},
    ]
