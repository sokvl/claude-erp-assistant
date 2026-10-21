import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from app.invoices.enums import LINE_ITEM_FIELDS, PERIOD_UNITS, GroupBy, InvoiceStatus
from app.invoices.schemas import InvoiceAnalyticsParams, InvoiceFilter
from app.limits import DEFAULT_ANALYTICS_ROWS, MAX_ANALYTICS_ROWS

MONTH_MARKER = "posting_month="


@dataclass(frozen=True)
class Grouping:
    key: str
    label: str | None
    joins: tuple[str, ...]


PERIOD = "JOIN read_parquet($dim_date) d ON d.date_key = f.posting_date_key"
PRODUCT = "JOIN read_parquet($dim_product) p ON p.sku = f.sku"
CUSTOMER = "LEFT JOIN read_parquet($dim_customer) c ON c.customer_number = f.customer_number"

GROUPINGS: Mapping[GroupBy | None, Grouping] = {
    None: Grouping("NULL", None, ()),
    GroupBy.CUSTOMER: Grouping("f.customer_number", "c.canonical_name", (CUSTOMER,)),
    GroupBy.MONTH: Grouping("strftime(make_date(d.year, d.month, 1), '%Y-%m-%d')", None, (PERIOD,)),
    GroupBy.QUARTER: Grouping("strftime(make_date(d.year, 3 * d.quarter - 2, 1), '%Y-%m-%d')", None, (PERIOD,)),
    GroupBy.YEAR: Grouping("strftime(make_date(d.year, 1, 1), '%Y-%m-%d')", None, (PERIOD,)),
    GroupBy.PRODUCT: Grouping("f.sku", "p.product_name", (PRODUCT,)),
    GroupBy.BRAND: Grouping("p.brand", None, (PRODUCT,)),
    GroupBy.CATEGORY: Grouping("p.category", None, (PRODUCT,)),
}
TABLE_PARAMETERS = (
    "fact_invoice",
    "fact_invoice_line",
    "dim_date",
    "dim_product",
    "dim_customer",
    "dim_customer_alias",
)


def to_date_key(day: date) -> int:
    return day.year * 10_000 + day.month * 100 + day.day


def read_month(file: str) -> str | None:
    if MONTH_MARKER not in file:
        return None
    return file.split(MONTH_MARKER, 1)[1][:7]


def select_month_files(files: Iterable[str], posted_from: date | None, posted_to: date | None) -> list[str]:
    first = f"{posted_from:%Y-%m}" if posted_from else None
    last = f"{posted_to:%Y-%m}" if posted_to else None
    selected = []
    for file in files:
        month = read_month(file)
        unbounded = month is None
        if unbounded or ((first is None or month >= first) and (last is None or month <= last)):
            selected.append(file)
    return selected


def build_conditions(filters: InvoiceFilter, as_of: date, line_grain: bool) -> tuple[list[str], dict[str, Any]]:
    conditions: list[str] = []
    values: dict[str, Any] = {}
    if filters.invoice_id:
        conditions.append("f.invoice_id = $invoice_id")
        values["invoice_id"] = filters.invoice_id
    if filters.posted_from:
        conditions.append("f.posting_date_key >= $posted_from")
        values["posted_from"] = to_date_key(filters.posted_from)
    if filters.posted_to:
        conditions.append("f.posting_date_key <= $posted_to")
        values["posted_to"] = to_date_key(filters.posted_to)
    if filters.customer:
        conditions.append(
            "(f.customer_number = $customer OR f.customer_number IN "
            "(SELECT customer_number FROM read_parquet($dim_customer_alias) WHERE starts_with(name_lower, $customer_prefix)))"
        )
        values["customer"] = filters.customer
        values["customer_prefix"] = filters.customer.lower()
    if filters.currency:
        conditions.append("f.currency = $currency")
        values["currency"] = filters.currency
    if filters.status is InvoiceStatus.OPEN:
        conditions.append("f.is_open")
    elif filters.status is InvoiceStatus.CLEARED:
        conditions.append("NOT f.is_open")
    elif filters.status is InvoiceStatus.OVERDUE:
        conditions.append("f.is_open AND f.due_date_key < $as_of")
    amount_conditions = []
    if filters.min_amount is not None:
        amount_conditions.append("amount >= $min_amount")
        values["min_amount"] = filters.min_amount
    if filters.max_amount is not None:
        amount_conditions.append("amount <= $max_amount")
        values["max_amount"] = filters.max_amount
    if amount_conditions and line_grain:
        conditions.append(
            f"f.invoice_id IN (SELECT invoice_id FROM read_parquet($fact_invoice) WHERE {' AND '.join(amount_conditions)})"
        )
    else:
        conditions += [f"f.{condition}" for condition in amount_conditions]
    return conditions, values


def half_even_division(numerator: str, denominator: str) -> str:
    quotient, remainder = f"(({numerator}) // ({denominator}))", f"(({numerator}) % ({denominator}))"
    return (
        f"({quotient} + CASE WHEN 2 * {remainder} > ({denominator}) THEN 1 "
        f"WHEN 2 * {remainder} = ({denominator}) AND {quotient} % 2 = 1 THEN 1 ELSE 0 END)"
    )


def build_per_invoice(grouping: Grouping, line_grain: bool, where: str) -> str:
    joins = " ".join(grouping.joins)
    if line_grain:
        return f"""
            SELECT {grouping.key} AS key, max({grouping.label or 'NULL'}) AS label, f.invoice_id,
                   any_value(f.currency) AS currency, sum(CAST(round(f.line_total * 100) AS BIGINT)) AS cents,
                   sum(f.quantity) AS units,
                   any_value(f.is_open) AS is_open, any_value(f.due_date_key) AS due_date_key,
                   any_value(f.days_to_pay) AS days_to_pay
            FROM read_parquet($fact_invoice_line) f {joins}
            {where}
            GROUP BY key, f.invoice_id"""
    return f"""
            SELECT {grouping.key} AS key, {grouping.label or 'NULL'} AS label, f.invoice_id, f.currency,
                   CAST(round(f.amount * 100) AS BIGINT) AS cents, NULL AS units, f.is_open, f.due_date_key, f.days_to_pay
            FROM read_parquet($fact_invoice) f {joins}
            {where}"""


def build_analytics_query(
    params: InvoiceAnalyticsParams, as_of: date, files: Mapping[str, Sequence[str]]
) -> tuple[str, dict[str, Any]]:
    group_by = params.group_by
    if group_by not in GROUPINGS:
        raise ValueError(f"group_by must be a GroupBy, got {group_by!r}")
    line_grain = group_by in LINE_ITEM_FIELDS
    conditions, values = build_conditions(params, as_of, line_grain)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    order = "key" if group_by in PERIOD_UNITS else "total_cents DESC, key"
    sql = f"""
        WITH per_invoice AS ({build_per_invoice(GROUPINGS[group_by], line_grain, where)}),
        groups AS (
            SELECT currency, key, max(label) AS label,
                   count(*) AS invoice_count,
                   sum(cents) AS total_cents,
                   sum(CASE WHEN is_open THEN cents ELSE 0 END) AS open_cents,
                   sum(CASE WHEN is_open AND due_date_key < $as_of THEN cents ELSE 0 END) AS overdue_cents,
                   sum(CASE WHEN NOT is_open THEN days_to_pay END) AS paid_days,
                   count(CASE WHEN NOT is_open THEN days_to_pay END) AS paid_invoices,
                   sum(units) AS units
            FROM per_invoice
            GROUP BY currency, key
        ),
        ranked AS (
            SELECT *, row_number() OVER (PARTITION BY currency ORDER BY {order}) AS position,
                   count(*) OVER (PARTITION BY currency) AS group_count
            FROM groups
        )
        SELECT currency, group_count, key, label, invoice_count,
               total_cents / 100.0 AS total_amount,
               {half_even_division("total_cents", "invoice_count")} / 100.0 AS average_amount,
               open_cents / 100.0 AS open_amount,
               overdue_cents / 100.0 AS overdue_amount,
               CASE WHEN paid_invoices > 0 THEN {half_even_division("10 * paid_days", "paid_invoices")} / 10.0 END
                   AS average_days_to_pay,
               units,
               CASE WHEN units > 0 THEN {half_even_division("total_cents", "units")} / 100.0 END AS average_unit_price
        FROM ranked
        WHERE position <= $rows
        ORDER BY currency, position"""
    values["as_of"] = to_date_key(as_of)
    values["rows"] = params.limit or (MAX_ANALYTICS_ROWS if group_by in PERIOD_UNITS else DEFAULT_ANALYTICS_ROWS)
    for table in TABLE_PARAMETERS:
        if re.search(rf"\${table}\b", sql):
            values[table] = list(files[table])
    return sql, values


def build_coverage_query(files: Sequence[str]) -> tuple[str, dict[str, Any]]:
    sql = "SELECT min(posting_date_key), max(posting_date_key) FROM read_parquet($fact_invoice)"
    return sql, {"fact_invoice": list(files)}
