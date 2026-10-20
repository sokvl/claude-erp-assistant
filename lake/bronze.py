from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import batched
from typing import Any

import pyarrow as pa
from pymongo import ReadPreference
from pymongo.read_concern import ReadConcern

from lake.loading import Target, load_partition
from lake.settings import Layer
from lake.storage import DEFAULT_BATCH_ROWS, Lake

DATASET = "invoices"
OVERLAP = timedelta(minutes=5)
TIMESTAMP = pa.timestamp("ms", tz="UTC")

CUSTOMER = pa.struct([("number", pa.string()), ("name", pa.string()), ("nameLower", pa.string())])
AMOUNTS = pa.struct([("totalOpen", pa.float64())])
DATES = pa.struct(
    [
        (name, TIMESTAMP)
        for name in ("postingDate", "documentCreateDate", "documentCreateDate1", "dueInDate", "baselineCreateDate", "clearDate")
    ]
)
LINE = pa.struct(
    [
        ("lineNo", pa.int64()),
        ("sku", pa.string()),
        ("productName", pa.string()),
        ("brand", pa.string()),
        ("category", pa.string()),
        ("quantity", pa.int64()),
        ("unitPrice", pa.float64()),
        ("lineTotal", pa.float64()),
    ]
)
BRONZE_SCHEMA = pa.schema(
    [
        ("_id", pa.string()),
        ("invoiceId", pa.string()),
        ("docId", pa.string()),
        ("businessCode", pa.string()),
        ("customer", CUSTOMER),
        ("currency", pa.string()),
        ("documentType", pa.string()),
        ("postingId", pa.int64()),
        ("isOpen", pa.bool_()),
        ("amounts", AMOUNTS),
        ("dates", DATES),
        ("paymentTerms", pa.string()),
        ("businessYear", pa.int64()),
        ("lines", pa.list_(LINE)),
        ("closedAt", TIMESTAMP),
        ("closedReason", pa.string()),
        ("source", pa.string()),
        ("updatedAt", TIMESTAMP),
        ("_extracted_at", TIMESTAMP),
    ]
)


@dataclass(frozen=True)
class Window:
    since: datetime | None
    until: datetime


@dataclass(frozen=True)
class BronzeLoad:
    rows: int
    unknown_fields: list[str]


def build_window(start: datetime, end: datetime, first: bool, overlap: timedelta = OVERLAP) -> Window:
    return Window(since=None if first else start - overlap, until=end)


def build_filter(window: Window) -> dict[str, Any]:
    bounds: dict[str, Any] = {"$lt": window.until}
    if window.since is not None:
        bounds["$gte"] = window.since
    return {"updatedAt": bounds}


def name_partition(start: datetime) -> str:
    return f"changed_at={start:%Y-%m-%d-%H}"


def read_source(collection: Any) -> Any:
    return collection.with_options(
        read_preference=ReadPreference.SECONDARY_PREFERRED, read_concern=ReadConcern("majority")
    )


def extract_batches(collection: Any, window: Window, batch_size: int = DEFAULT_BATCH_ROWS) -> Iterator[tuple[dict, ...]]:
    cursor = read_source(collection).find(build_filter(window), sort=[("updatedAt", 1), ("_id", 1)], batch_size=batch_size)
    return batched(cursor, batch_size)


def count_window(collection: Any, window: Window) -> int:
    return read_source(collection).count_documents(build_filter(window))


def to_table(documents: Iterable[Mapping[str, Any]], extracted_at: datetime) -> pa.Table:
    rows = [{**document, "_extracted_at": extracted_at} for document in documents]
    return pa.Table.from_pylist(rows, schema=BRONZE_SCHEMA)


def find_unknown_fields(document: Mapping[str, Any], fields: Iterable[pa.Field] = BRONZE_SCHEMA, prefix: str = "") -> set[str]:
    known = {field.name: field.type for field in fields}
    unknown = {f"{prefix}{name}" for name in document if name not in known}
    for name, value in document.items():
        kind = known.get(name)
        if isinstance(kind, pa.StructType) and isinstance(value, Mapping):
            unknown |= find_unknown_fields(value, kind, f"{prefix}{name}.")
        if isinstance(kind, pa.ListType) and isinstance(kind.value_type, pa.StructType) and isinstance(value, list):
            for item in value:
                unknown |= find_unknown_fields(item, kind.value_type, f"{prefix}{name}[].")
    return unknown


def load_bronze(
    lake: Lake,
    collection: Any,
    window: Window,
    partition: str,
    extracted_at: datetime,
    batch_size: int = DEFAULT_BATCH_ROWS,
) -> BronzeLoad:
    unknown: set[str] = set()

    def convert(documents: tuple[dict, ...]) -> pa.Table:
        for document in documents:
            unknown.update(find_unknown_fields(document))
        return to_table(documents, extracted_at)

    target = Target(Layer.BRONZE, DATASET, partition, empty_schema=BRONZE_SCHEMA)
    rows = load_partition(lake, target, extract_batches(collection, window, batch_size), convert)
    return BronzeLoad(rows=rows, unknown_fields=sorted(unknown))
