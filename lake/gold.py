from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pandas as pd
import pyarrow as pa

from lake.settings import Layer
from lake.silver import CUSTOMER_SCHEMA, CUSTOMERS, INVOICE_SCHEMA, INVOICES, LINE_SCHEMA, LINES, convert_to_arrow
from lake.storage import Lake

DATE_ROLES = {"posting_date": "posting_date_key", "due_date": "due_date_key", "clear_date": "payment_date_key"}
DATE_KEYS = list(DATE_ROLES.values())
HEADER_COPIES = ["currency", "customer_number", *DATE_KEYS, "is_open", "days_to_pay"]
FLAGS = pa.list_(pa.string())

DIM_DATE_SCHEMA = pa.schema(
    [
        ("date_key", pa.int32()),
        ("date", pa.date32()),
        ("year", pa.int32()),
        ("quarter", pa.int32()),
        ("month", pa.int32()),
        ("year_month", pa.string()),
        ("iso_week", pa.int32()),
        ("day_of_week", pa.int32()),
        ("is_weekend", pa.bool_()),
    ]
)
DIM_CUSTOMER_SCHEMA = pa.schema([("customer_number", pa.string()), ("canonical_name", pa.string()), ("alias_count", pa.int64())])
DIM_PRODUCT_SCHEMA = pa.schema(
    [("sku", pa.string()), ("product_name", pa.string()), ("brand", pa.string()), ("category", pa.string())]
)
FACT_INVOICE_SCHEMA = pa.schema(
    [
        ("invoice_id", pa.string()),
        ("customer_number", pa.string()),
        *[(key, pa.int32()) for key in DATE_KEYS],
        ("currency", pa.string()),
        ("document_type", pa.string()),
        ("payment_terms", pa.string()),
        ("amount", pa.float64()),
        ("is_open", pa.bool_()),
        ("days_to_pay", pa.int64()),
        ("paid_late", pa.bool_()),
        ("line_count", pa.int64()),
        ("quality_flags", FLAGS),
    ]
)
FACT_INVOICE_LINE_SCHEMA = pa.schema(
    [
        ("invoice_id", pa.string()),
        ("line_no", pa.int64()),
        ("sku", pa.string()),
        ("quantity", pa.int64()),
        ("unit_price", pa.float64()),
        ("line_total", pa.float64()),
        ("currency", pa.string()),
        ("customer_number", pa.string()),
        *[(key, pa.int32()) for key in DATE_KEYS],
        ("is_open", pa.bool_()),
        ("days_to_pay", pa.int64()),
    ]
)


def to_date_key(dates: pd.Series) -> pd.Series:
    return (dates.dt.year * 10_000 + dates.dt.month * 100 + dates.dt.day).astype("Int64")


def build_dim_date(invoices: pd.DataFrame) -> pd.DataFrame:
    dates = pd.concat([invoices[column] for column in DATE_ROLES], ignore_index=True).dropna()
    if dates.empty:
        return DIM_DATE_SCHEMA.empty_table().to_pandas()
    days = pd.Series(pd.date_range(dates.min().normalize(), dates.max().normalize(), freq="D"))
    iso = days.dt.isocalendar()
    return pd.DataFrame(
        {
            "date_key": to_date_key(days),
            "date": days.dt.date,
            "year": days.dt.year,
            "quarter": days.dt.quarter,
            "month": days.dt.month,
            "year_month": days.dt.strftime("%Y-%m"),
            "iso_week": iso["week"].astype("int64"),
            "day_of_week": days.dt.dayofweek + 1,
            "is_weekend": days.dt.dayofweek >= 5,
        }
    )


def build_dim_customer(customers: pd.DataFrame) -> pd.DataFrame:
    return customers[DIM_CUSTOMER_SCHEMA.names].sort_values("customer_number").reset_index(drop=True)


def build_dim_product(lines: pd.DataFrame, invoices: pd.DataFrame) -> pd.DataFrame:
    sold = lines.merge(invoices[["invoice_id", "posting_date"]], on="invoice_id", how="inner")
    latest = sold.sort_values(["sku", "posting_date", "invoice_id", "line_no"]).drop_duplicates("sku", keep="last")
    return latest[DIM_PRODUCT_SCHEMA.names].reset_index(drop=True)


def build_fact_invoice(invoices: pd.DataFrame, lines: pd.DataFrame) -> pd.DataFrame:
    facts = invoices.copy()
    for column, key in DATE_ROLES.items():
        facts[key] = to_date_key(facts[column])
    line_counts = lines.groupby("invoice_id").size()
    facts["line_count"] = facts["invoice_id"].map(line_counts).fillna(0).astype("int64")
    return facts[FACT_INVOICE_SCHEMA.names].sort_values("invoice_id").reset_index(drop=True)


def build_fact_invoice_line(lines: pd.DataFrame, fact_invoice: pd.DataFrame) -> pd.DataFrame:
    own = ["invoice_id", "line_no", "sku", "quantity", "unit_price", "line_total"]
    facts = lines[own].merge(fact_invoice[["invoice_id", *HEADER_COPIES]], on="invoice_id", how="inner")
    return facts[FACT_INVOICE_LINE_SCHEMA.names].sort_values(["invoice_id", "line_no"]).reset_index(drop=True)


TABLE_SCHEMAS: Mapping[str, pa.Schema] = {
    "dim_date": DIM_DATE_SCHEMA,
    "dim_customer": DIM_CUSTOMER_SCHEMA,
    "dim_product": DIM_PRODUCT_SCHEMA,
    "fact_invoice": FACT_INVOICE_SCHEMA,
    "fact_invoice_line": FACT_INVOICE_LINE_SCHEMA,
}
FACT_TABLES = ("fact_invoice", "fact_invoice_line")
POINTER = "_current.json"
KEEP_VERSIONS = 3
WHOLE_TABLE = "all"


@dataclass(frozen=True)
class GoldRun:
    version: str
    rows: dict[str, int]
    removed: list[str]


def build_gold(invoices: pd.DataFrame, lines: pd.DataFrame, customers: pd.DataFrame) -> dict[str, pd.DataFrame]:
    fact_invoice = build_fact_invoice(invoices, lines)
    return {
        "dim_date": build_dim_date(invoices),
        "dim_customer": build_dim_customer(customers),
        "dim_product": build_dim_product(lines, invoices),
        "fact_invoice": fact_invoice,
        "fact_invoice_line": build_fact_invoice_line(lines, fact_invoice),
    }


def name_version(now: datetime) -> str:
    return f"v={now:%Y%m%dT%H%M%S%fZ}"


def split_by_month(facts: pd.DataFrame) -> list[tuple[str, pd.DataFrame]]:
    months = facts["posting_date_key"] // 100
    return [(f"posting_month={month // 100:04d}-{month % 100:02d}", rows) for month, rows in facts.groupby(months)]


def write_version(lake: Lake, tables: Mapping[str, pd.DataFrame], version: str) -> dict[str, list[str]]:
    files: dict[str, list[str]] = {}
    for name, frame in tables.items():
        schema = TABLE_SCHEMAS[name]
        parts = split_by_month(frame) if name in FACT_TABLES and not frame.empty else [(WHOLE_TABLE, frame)]
        files[name] = []
        for part, rows in parts:
            partition = f"{version}/{part}"
            lake.replace_partition(Layer.GOLD, name, partition, [convert_to_arrow(rows, schema)], empty_schema=schema)
            files[name] += [lake.to_relative(Layer.GOLD, file) for file in lake.list_part_files(Layer.GOLD, name, [partition])]
    return files


def build_pointer(
    previous: Mapping[str, Any] | None, version: str, files: Mapping[str, list[str]], rows: Mapping[str, int], now: datetime
) -> dict[str, Any]:
    retained = [] if previous is None else [*previous["retained"], previous["version"]][-(KEEP_VERSIONS - 1):]
    return {"version": version, "published_at": now.isoformat(), "tables": dict(files), "rows": dict(rows), "retained": retained}


def find_unreferenced_versions(stored: Mapping[str, list[str]], pointer: Mapping[str, Any]) -> list[tuple[str, str]]:
    keep = {pointer["version"], *pointer["retained"]}
    return [(name, version) for name, versions in stored.items() for version in versions if version not in keep]


def read_current(lake: Lake) -> dict[str, Any] | None:
    return lake.read_pointer(Layer.GOLD, POINTER)


def read_gold_table(lake: Lake, pointer: Mapping[str, Any], name: str) -> pa.Table:
    return lake.read_files(Layer.GOLD, pointer["tables"][name], TABLE_SCHEMAS[name])


def materialize_gold(lake: Lake, now: datetime) -> GoldRun:
    invoices = lake.read_dataset(Layer.SILVER, INVOICES, schema=INVOICE_SCHEMA).to_pandas()
    lines = lake.read_dataset(Layer.SILVER, LINES, schema=LINE_SCHEMA).to_pandas()
    customers = lake.read_dataset(Layer.SILVER, CUSTOMERS, schema=CUSTOMER_SCHEMA).to_pandas()
    tables = build_gold(invoices, lines, customers)
    version = name_version(now)
    files = write_version(lake, tables, version)
    rows = {name: len(frame) for name, frame in tables.items()}
    pointer = build_pointer(read_current(lake), version, files, rows, now)
    lake.write_pointer(Layer.GOLD, POINTER, pointer)
    stored = {name: lake.list_partitions(Layer.GOLD, name) for name in TABLE_SCHEMAS}
    removed = find_unreferenced_versions(stored, pointer)
    for name, old in removed:
        lake.delete_partition(Layer.GOLD, name, old)
    return GoldRun(version=version, rows=rows, removed=[f"{name}/{old}" for name, old in removed])
