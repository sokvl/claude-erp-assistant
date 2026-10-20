from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc

from lake.bronze import BRONZE_SCHEMA, LINE, TIMESTAMP
from lake.bronze import DATASET as BRONZE_DATASET
from lake.settings import Layer
from lake.storage import Lake

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
LOCATION = [*VERSION, "posting_month"]
CENT = 0.01

INVOICES = "invoices"
LINES = "invoice_lines"
REJECTED = "invoices_rejected"
REJECTED_LINES = "invoice_lines_rejected"
STATE = "_invoices_state.json"
PROCESSED = "processed_bronze_partitions"

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


@dataclass(frozen=True)
class MonthResult:
    invoices: pd.DataFrame
    lines: pd.DataFrame
    rejected: pd.DataFrame
    rejected_lines: pd.DataFrame


@dataclass(frozen=True)
class SilverRun:
    bronze_partitions: list[str]
    months: list[str]
    invoices: int
    rejected: int


def name_invoice_columns(bronze: pa.Table) -> pa.Table:
    flat = bronze.drop_columns(["lines"]).flatten()
    return flat.select(list(INVOICE_COLUMNS)).rename_columns(list(INVOICE_COLUMNS.values()))


FLAGS = pa.list_(pa.string())
BASE_SCHEMA = name_invoice_columns(BRONZE_SCHEMA.empty_table()).schema
INVOICE_SCHEMA = pa.schema(
    [
        *BASE_SCHEMA,
        ("days_to_pay", pa.int64()),
        ("paid_late", pa.bool_()),
        ("posting_month", pa.string()),
        ("lines_total", pa.float64()),
        ("quality_flags", FLAGS),
    ]
)
REJECTED_SCHEMA = INVOICE_SCHEMA.append(pa.field("rejection_reasons", FLAGS))
LINE_SCHEMA = pa.schema(
    [
        ("invoice_id", pa.string()),
        ("updated_at", TIMESTAMP),
        ("extracted_at", TIMESTAMP),
        *[(LINE_COLUMNS[field.name], field.type) for field in LINE],
        ("posting_month", pa.string()),
    ]
)


def flatten_invoices(bronze: pa.Table) -> pd.DataFrame:
    return name_invoice_columns(bronze).to_pandas()


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
    kept = lines.merge(latest_invoices[VERSION], on=VERSION, how="inner").drop_duplicates(["invoice_id", "line_no"])
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


def build_month_partition(month: str) -> str:
    return f"posting_month={month}"


def find_pending(bronze_partitions: Iterable[str], processed: Iterable[str]) -> list[str]:
    return sorted(set(bronze_partitions) - set(processed))


def find_winning_months(new_invoices: pd.DataFrame, previous_locations: pd.DataFrame) -> pd.Series:
    all_versions = concatenate_frames([previous_locations[LOCATION], new_invoices[LOCATION]])
    return keep_latest(all_versions).set_index("invoice_id")["posting_month"]


def merge_month(
    month: str,
    current_invoices: pd.DataFrame,
    current_lines: pd.DataFrame,
    new_invoices: pd.DataFrame,
    new_lines: pd.DataFrame,
    winning_month_by_invoice: pd.Series,
) -> MonthResult:
    columns = BASE_SCHEMA.names
    latest_versions = keep_latest(concatenate_frames([current_invoices[columns], new_invoices[columns]]))
    winning_month = latest_versions["invoice_id"].map(winning_month_by_invoice)
    belongs_here = winning_month.isna() | (winning_month == month)
    invoices = latest_versions[belongs_here].reset_index(drop=True)
    lines = keep_latest_lines(concatenate_frames([current_lines, new_lines]), invoices)
    validated = validate(derive(standardize(invoices)), lines)
    is_accepted_line = lines["invoice_id"].isin(validated.invoices["invoice_id"])
    return MonthResult(
        invoices=validated.invoices,
        lines=lines[is_accepted_line].reset_index(drop=True),
        rejected=validated.rejected,
        rejected_lines=lines[~is_accepted_line].reset_index(drop=True),
    )


def merge_silver(lake: Lake) -> SilverRun:
    processed = (lake.read_pointer(Layer.SILVER, STATE) or {}).get(PROCESSED, [])
    pending = find_pending(lake.list_partitions(Layer.BRONZE, BRONZE_DATASET), processed)
    if not pending:
        return SilverRun(bronze_partitions=[], months=[], invoices=0, rejected=0)
    bronze = lake.read_dataset(Layer.BRONZE, BRONZE_DATASET, pending, schema=BRONZE_SCHEMA)
    new_invoices = keep_latest(flatten_invoices(bronze))
    new_invoices["posting_month"] = name_month(new_invoices["posting_date"])
    new_lines = keep_latest_lines(explode_lines(bronze), new_invoices)
    stored_locations = read_stored_locations(lake)
    previous_locations = stored_locations[stored_locations["invoice_id"].isin(new_invoices["invoice_id"])]
    winning_month_by_invoice = find_winning_months(new_invoices, previous_locations)
    months = sorted(set(new_invoices["posting_month"].dropna()) | set(previous_locations["posting_month"]))
    new_invoices_by_month = dict(list(new_invoices.groupby("posting_month")))
    new_lines_by_month = dict(list(new_lines.groupby("posting_month")))
    accepted_count = rejected_count = 0
    for month in months:
        result = merge_month(
            month,
            read_stored_month(lake, INVOICES, REJECTED, month, INVOICE_SCHEMA, REJECTED_SCHEMA),
            read_stored_month(lake, LINES, REJECTED_LINES, month, LINE_SCHEMA, LINE_SCHEMA),
            new_invoices_by_month.get(month, new_invoices.iloc[:0]),
            new_lines_by_month.get(month, new_lines.iloc[:0]),
            winning_month_by_invoice,
        )
        write_month(lake, month, result)
        accepted_count += len(result.invoices)
        rejected_count += len(result.rejected)
    lake.write_pointer(Layer.SILVER, STATE, {PROCESSED: sorted({*processed, *pending})})
    return SilverRun(bronze_partitions=pending, months=months, invoices=accepted_count, rejected=rejected_count)


def read_stored_locations(lake: Lake) -> pd.DataFrame:
    tables = [
        lake.read_dataset(Layer.SILVER, dataset, columns=LOCATION, schema=schema).select(LOCATION)
        for dataset, schema in ((INVOICES, INVOICE_SCHEMA), (REJECTED, REJECTED_SCHEMA))
    ]
    return pa.concat_tables(tables).to_pandas()


def read_stored_month(
    lake: Lake, accepted_dataset: str, rejected_dataset: str, month: str, schema: pa.Schema, rejected_schema: pa.Schema
) -> pd.DataFrame:
    partition = [build_month_partition(month)]
    tables = [
        lake.read_dataset(Layer.SILVER, accepted_dataset, partition, schema=schema).select(schema.names),
        lake.read_dataset(Layer.SILVER, rejected_dataset, partition, schema=rejected_schema).select(schema.names),
    ]
    return pa.concat_tables(tables).to_pandas()


def write_month(lake: Lake, month: str, result: MonthResult) -> None:
    partition = build_month_partition(month)
    outputs = (
        (INVOICES, result.invoices, INVOICE_SCHEMA),
        (LINES, result.lines, LINE_SCHEMA),
        (REJECTED, result.rejected, REJECTED_SCHEMA),
        (REJECTED_LINES, result.rejected_lines, LINE_SCHEMA),
    )
    for dataset, frame, schema in outputs:
        lake.replace_partition(Layer.SILVER, dataset, partition, [convert_to_arrow(frame, schema)])


def convert_to_arrow(frame: pd.DataFrame, schema: pa.Schema) -> pa.Table:
    return pa.Table.from_pandas(frame[schema.names], schema=schema, preserve_index=False)


def concatenate_frames(frames: list[pd.DataFrame]) -> pd.DataFrame:
    non_empty = [frame for frame in frames if not frame.empty]
    if not non_empty:
        return frames[0]
    return pd.concat(non_empty, ignore_index=True)
