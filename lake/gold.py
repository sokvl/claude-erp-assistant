import pandas as pd
import pyarrow as pa

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
