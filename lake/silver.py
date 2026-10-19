from collections.abc import Callable, Mapping
from dataclasses import dataclass

import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc

INVOICE_COLUMNS = {
    "_id": "invoice_id",
    "businessCode": "business_code",
    "customer.number": "customer_number",
    "customer.name": "customer_name",
    "currency": "currency",
    "documentType": "document_type",
    "paymentTerms": "payment_terms",
    "isOpen": "is_open",
    "amounts.totalOpen": "amount",
    "dates.postingDate": "posting_date",
    "dates.documentCreateDate": "document_date",
    "dates.dueInDate": "due_date",
    "dates.baselineCreateDate": "baseline_date",
    "dates.clearDate": "clear_date",
    "closedAt": "closed_at",
    "source": "source",
    "updatedAt": "updated_at",
    "_extracted_at": "extracted_at",
}
LINE_COLUMNS = {
    "lineNo": "line_no",
    "sku": "sku",
    "productName": "product_name",
    "brand": "brand",
    "category": "category",
    "quantity": "quantity",
    "unitPrice": "unit_price",
    "lineTotal": "line_total",
}
VERSION = ["invoice_id", "updated_at", "extracted_at"]
CENT = 0.01

Rule = Callable[[pd.DataFrame], pd.Series]

HARD_RULES: Mapping[str, Rule] = {
    "missing_posting_date": lambda frame: frame["posting_date"].isna(),
    "amount_not_positive": lambda frame: ~(frame["amount"] > 0),
    "invalid_currency": lambda frame: ~frame["currency"].str.fullmatch(r"[A-Z]{3}").fillna(False).astype(bool),
    "cleared_before_posting": lambda frame: frame["clear_date"] < frame["posting_date"],
    "open_with_clear_date": lambda frame: frame["is_open"] & frame["clear_date"].notna(),
}
SOFT_RULES: Mapping[str, Rule] = {
    "due_before_posting": lambda frame: frame["due_date"] < frame["posting_date"],
    "closed_without_payment_date": lambda frame: ~frame["is_open"] & frame["clear_date"].isna(),
    "lines_do_not_match_amount": lambda frame: ~((frame["lines_total"] - frame["amount"]).abs().round(2) <= CENT),
}


@dataclass(frozen=True)
class Validated:
    invoices: pd.DataFrame
    rejected: pd.DataFrame


def flatten_invoices(bronze: pa.Table) -> pd.DataFrame:
    flat = bronze.drop_columns(["lines"]).flatten()
    return flat.select(list(INVOICE_COLUMNS)).rename_columns(list(INVOICE_COLUMNS.values())).to_pandas()


def explode_lines(bronze: pa.Table) -> pd.DataFrame:
    table = bronze.combine_chunks()
    lines = pa.concat_arrays(table["lines"].chunks) if table["lines"].num_chunks else pa.array([], table.schema.field("lines").type)
    parents = pc.list_parent_indices(lines)
    items = pc.list_flatten(lines)
    columns = {
        "invoice_id": table["_id"].take(parents),
        "posting_date": pc.struct_field(table["dates"], "postingDate").take(parents),
        "updated_at": table["updatedAt"].take(parents),
        "extracted_at": table["_extracted_at"].take(parents),
        **{silver: pc.struct_field(items, bronze_name) for bronze_name, silver in LINE_COLUMNS.items()},
    }
    frame = pa.table(columns).to_pandas()
    frame["posting_month"] = name_month(frame["posting_date"])
    return frame.drop(columns=["posting_date"])


def keep_latest(invoices: pd.DataFrame) -> pd.DataFrame:
    ordered = invoices.sort_values(VERSION)
    return ordered.drop_duplicates("invoice_id", keep="last").reset_index(drop=True)


def keep_latest_lines(lines: pd.DataFrame, latest_invoices: pd.DataFrame) -> pd.DataFrame:
    kept = lines.merge(latest_invoices[VERSION], on=VERSION, how="inner")
    return kept.sort_values(["invoice_id", "line_no"]).reset_index(drop=True)


def standardize(invoices: pd.DataFrame) -> pd.DataFrame:
    frame = invoices.copy()
    frame["customer_name"] = collapse_whitespace(frame["customer_name"])
    frame["currency"] = frame["currency"].str.strip().str.upper()
    return frame


def derive(invoices: pd.DataFrame) -> pd.DataFrame:
    frame = invoices.copy()
    paid = frame["clear_date"].notna()
    calendar_days = (frame["clear_date"].dt.normalize() - frame["posting_date"].dt.normalize()).dt.days
    frame["days_to_pay"] = calendar_days.where(paid).astype("Int64")
    frame["paid_late"] = (frame["clear_date"] > frame["due_date"]).astype("boolean").mask(~paid)
    frame["posting_month"] = name_month(frame["posting_date"])
    return frame


def validate(invoices: pd.DataFrame, lines: pd.DataFrame) -> Validated:
    totals = lines.groupby("invoice_id")["line_total"].sum().round(2)
    frame = invoices.assign(lines_total=invoices["invoice_id"].map(totals))
    hard = evaluate_rules(frame, HARD_RULES)
    rejected = hard.any(axis=1)
    frame["quality_flags"] = collect_names(evaluate_rules(frame, SOFT_RULES))
    accepted = frame[~rejected].reset_index(drop=True)
    refused = frame[rejected].assign(rejection_reasons=collect_names(hard)[rejected]).reset_index(drop=True)
    return Validated(invoices=accepted, rejected=refused)


def evaluate_rules(frame: pd.DataFrame, rules: Mapping[str, Rule]) -> pd.DataFrame:
    return pd.DataFrame({name: rule(frame).fillna(False).astype(bool) for name, rule in rules.items()}, index=frame.index)


def collect_names(hits: pd.DataFrame) -> pd.Series:
    names = list(hits.columns)
    return pd.Series([[name for name, hit in zip(names, row) if hit] for row in hits.to_numpy()], index=hits.index, dtype=object)


def collapse_whitespace(values: pd.Series) -> pd.Series:
    return values.str.strip().str.replace(r"\s+", " ", regex=True)


def name_month(dates: pd.Series) -> pd.Series:
    return dates.dt.strftime("%Y-%m")
