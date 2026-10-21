import os
from collections.abc import Iterable, Mapping
from datetime import date
from functools import cache
from typing import Any

from app.analytics.gold import GoldVersion, load_reader_settings, open_gold
from app.analytics.query import build_analytics_query, build_coverage_query, select_month_files
from app.invoices.enums import LINE_ITEM_FIELDS, GroupBy
from app.invoices.schemas import InvoiceAnalyticsParams
from app.utils.dates import today_in_business_timezone
from app.vault import app_secrets
from lake_config.settings import LakeSettings

FACT_TABLES = ("fact_invoice", "fact_invoice_line")
MEASURES = {
    "invoice_count": "invoiceCount",
    "total_amount": "totalAmount",
    "average_amount": "averageAmount",
    "open_amount": "openAmount",
    "overdue_amount": "overdueAmount",
    "average_days_to_pay": "averageDaysToPay",
}


@cache
def get_gold_settings() -> LakeSettings | None:
    return load_reader_settings({**os.environ, **app_secrets()})


def select_files(version: GoldVersion, params: InvoiceAnalyticsParams) -> dict[str, list[str]]:
    return {
        name: select_month_files(files, params.posted_from, params.posted_to) if name in FACT_TABLES else list(files)
        for name, files in version.tables.items()
    }


def format_date_key(key: int | None) -> str | None:
    if key is None:
        return None
    return date(key // 10_000, key // 100 % 100, key % 100).isoformat()


def shape_row(row: Mapping[str, Any], group_by: GroupBy | None) -> dict[str, Any]:
    shaped: dict[str, Any] = {} if group_by is None else {"key": row["key"]}
    if group_by in (GroupBy.CUSTOMER, GroupBy.PRODUCT):
        shaped["label"] = row["label"]
    shaped |= {name: row[column] for column, name in MEASURES.items()}
    if group_by in LINE_ITEM_FIELDS:
        shaped["units"] = row["units"]
    if group_by is GroupBy.PRODUCT:
        shaped["averageUnitPrice"] = row["average_unit_price"]
    return shaped


def shape_currencies(rows: Iterable[Mapping[str, Any]], group_by: GroupBy | None) -> list[dict[str, Any]]:
    currencies: dict[str, dict[str, Any]] = {}
    for row in rows:
        entry = currencies.setdefault(row["currency"], {"currency": row["currency"], "groupCount": row["group_count"], "rows": []})
        entry["rows"].append(shape_row(row, group_by))
    return list(currencies.values())


def analyze_gold(settings: LakeSettings | None, params: InvoiceAnalyticsParams) -> dict[str, Any]:
    as_of = params.as_of or today_in_business_timezone()
    with open_gold(settings) as (connection, version):
        sql, values = build_analytics_query(params, as_of, select_files(version, params))
        cursor = connection.execute(sql, values)
        names = [column[0] for column in cursor.description]
        rows = [dict(zip(names, row)) for row in cursor.fetchall()]
        first, last = connection.execute(*build_coverage_query(version.tables["fact_invoice"])).fetchone()
    return {
        "asOf": as_of.isoformat(),
        "dataAsOf": version.data_as_of.isoformat() if version.data_as_of else None,
        "groupBy": params.group_by,
        "filters": params.model_dump(mode="json", exclude_none=True, exclude={"as_of", "group_by", "limit"}),
        "coverage": {"firstPostingDate": format_date_key(first), "lastPostingDate": format_date_key(last)},
        "currencies": shape_currencies(rows, params.group_by),
    }
