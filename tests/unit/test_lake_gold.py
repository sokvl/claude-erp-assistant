from datetime import UTC, date, datetime
from uuid import uuid4

import pandas as pd
import pyarrow as pa
import pytest

from lake.bronze import DATASET as BRONZE_DATASET
from lake.bronze import to_table
from lake.gold import (
    DIM_DATE_SCHEMA,
    DIM_PRODUCT_SCHEMA,
    FACT_INVOICE_LINE_SCHEMA,
    FACT_INVOICE_SCHEMA,
    build_dim_customer,
    build_dim_date,
    build_dim_product,
    build_fact_invoice,
    build_fact_invoice_line,
    build_pointer,
    find_unreferenced_versions,
    materialize_gold,
    name_version,
    read_current,
    read_gold_table,
    split_by_month,
    to_date_key,
)
from lake.settings import LakeSettings, Layer
from lake.silver import merge_silver
from lake.storage import Lake


def _day(text):
    return pd.Timestamp(text, tz="UTC") if text else pd.NaT


def _invoices(*rows):
    defaults = {"customer_number": "0100001196", "currency": "USD", "document_type": "RV", "payment_terms": "NAA8",
                "amount": 100.0, "is_open": True, "days_to_pay": pd.NA, "paid_late": pd.NA, "quality_flags": []}
    frame = pd.DataFrame([{**defaults, **row} for row in rows])
    for column in ("posting_date", "due_date", "clear_date"):
        frame[column] = pd.to_datetime(frame[column].map(_day), utc=True)
    return frame.astype({"days_to_pay": "Int64", "paid_late": "boolean"})


def _invoice(key="S1", posted="2026-09-01", due="2026-09-16", paid=None, **changes):
    closed = {"is_open": False, "days_to_pay": (_day(paid) - _day(posted)).days} if paid else {}
    return {"invoice_id": key, "posting_date": posted, "due_date": due, "clear_date": paid, **closed, **changes}


def _lines(*rows):
    defaults = {"line_no": 1, "sku": "LAP-DELL-7450", "product_name": "Latitude 7450", "brand": "Dell",
                "category": "Laptop", "quantity": 1, "unit_price": 100.0, "line_total": 100.0}
    return pd.DataFrame([{**defaults, **row} for row in rows])


@pytest.mark.parametrize(
    ("text", "expected"),
    [("2026-09-01 23:30", 20260901), ("2019-12-28", 20191228), (None, pd.NA)],
    ids=["keeps_the_utc_day", "earlier_year", "missing_date_stays_missing"],
)
def test_to_date_key_reads_as_yyyymmdd(text, expected):
    # Arrange / Act
    key = to_date_key(pd.Series([_day(text)], dtype="datetime64[ns, UTC]")).iloc[0]

    # Assert
    assert str(key) == str(expected)


# One calendar serves three roles, so it spans every date any role points at: a due date before the
# first posting, a payment after the last one, and a due date in the future. Unpaid invoices add
# nothing, and no day is skipped, so a daily chart shows zero instead of jumping over a quiet day.
def test_build_dim_date_spans_every_role_without_gaps():
    # Arrange
    invoices = _invoices(
        _invoice("S1", posted="2020-01-02", due="2019-12-28"),
        _invoice("S2", posted="2025-12-30", due="2026-01-14", paid="2026-01-15"),
        _invoice("S3", posted="2026-01-10", due="2026-02-24"),
    )

    # Act
    calendar = build_dim_date(invoices)

    # Assert
    assert (calendar["date_key"].iloc[0], calendar["date_key"].iloc[-1]) == (20191228, 20260224)
    assert len(calendar) == (date(2026, 2, 24) - date(2019, 12, 28)).days + 1
    assert calendar["date_key"].is_unique


def test_build_dim_date_describes_each_day():
    # Arrange
    invoices = _invoices(_invoice("S1", posted="2026-09-05", due="2026-09-05"))

    # Act
    row = build_dim_date(invoices).iloc[0]

    # Assert
    assert row.to_dict() == {
        "date_key": 20260905, "date": date(2026, 9, 5), "year": 2026, "quarter": 3, "month": 9,
        "year_month": "2026-09", "iso_week": 36, "day_of_week": 6, "is_weekend": True,
    }


def test_build_dim_date_without_invoices_is_empty_with_its_columns():
    # Arrange / Act
    calendar = build_dim_date(_invoices(_invoice()).iloc[:0])

    # Assert
    assert (calendar.empty, list(calendar.columns)) == (True, DIM_DATE_SCHEMA.names)


def test_build_dim_customer_keeps_number_canonical_name_and_alias_count():
    # Arrange
    customers = pd.DataFrame({"customer_number": ["2", "1"], "canonical_name": ["GEOR", "DOLLAR"], "alias_count": [2, 11]})

    # Act
    dimension = build_dim_customer(customers)

    # Assert
    assert dimension.values.tolist() == [["1", "DOLLAR", 11], ["2", "GEOR", 2]]


# The catalog renames products on purpose, so the newest sale names the product (SCD type 1). All
# attributes come from that one sale, so a new name never meets an old category.
@pytest.mark.parametrize(
    "order",
    [["S1", "S2"], ["S2", "S1"]],
    ids=["older_sale_first", "newer_sale_first"],
)
def test_build_dim_product_takes_every_attribute_from_the_latest_sale(order):
    # Arrange
    invoices = _invoices(_invoice("S1", posted="2024-03-01"), _invoice("S2", posted="2026-09-01"))
    sales = {
        "S1": {"invoice_id": "S1", "product_name": "Latitude 7450", "category": "Laptop"},
        "S2": {"invoice_id": "S2", "product_name": "Latitude 7450 (2026)", "category": "Workstation"},
    }

    # Act
    dimension = build_dim_product(_lines(*[sales[key] for key in order]), invoices)

    # Assert
    assert dimension.to_dict("records") == [
        {"sku": "LAP-DELL-7450", "product_name": "Latitude 7450 (2026)", "brand": "Dell", "category": "Workstation"}
    ]
    assert list(dimension.columns) == DIM_PRODUCT_SCHEMA.names


def test_build_fact_invoice_turns_dates_into_role_keys_and_counts_lines():
    # Arrange
    invoices = _invoices(_invoice("S1", paid="2026-09-10"), _invoice("S2"))
    lines = _lines({"invoice_id": "S1", "line_no": 1}, {"invoice_id": "S1", "line_no": 2})

    # Act
    facts = build_fact_invoice(invoices, lines)

    # Assert
    columns = ["invoice_id", "posting_date_key", "due_date_key", "payment_date_key", "is_open", "days_to_pay", "line_count"]
    assert [[str(value) for value in row] for row in facts[columns].values.tolist()] == [
        ["S1", "20260901", "20260916", "20260910", "False", "9", "2"],
        ["S2", "20260901", "20260916", "<NA>", "True", "<NA>", "0"],
    ]
    assert list(facts.columns) == FACT_INVOICE_SCHEMA.names


# Brand revenue per currency and quarter must not join two fact tables: each line carries the
# header attributes the analyst filters and groups lines by.
def test_build_fact_invoice_line_copies_the_header_attributes_lines_are_queried_by():
    # Arrange
    invoices = _invoices(_invoice("S1", paid="2026-09-10", currency="CAD", customer_number="0200769623"))
    lines = _lines({"invoice_id": "S1", "line_no": 2, "line_total": 40.0}, {"invoice_id": "S1", "line_no": 1, "line_total": 60.0})
    header = build_fact_invoice(invoices, lines)

    # Act
    facts = build_fact_invoice_line(lines, header)

    # Assert
    copied = ["line_no", "line_total", "currency", "customer_number", "posting_date_key", "payment_date_key", "is_open", "days_to_pay"]
    assert facts[copied].values.tolist() == [
        [1, 60.0, "CAD", "0200769623", 20260901, 20260910, False, 9],
        [2, 40.0, "CAD", "0200769623", 20260901, 20260910, False, 9],
    ]
    assert list(facts.columns) == FACT_INVOICE_LINE_SCHEMA.names


def test_build_fact_invoice_line_drops_lines_without_a_header():
    # Arrange
    invoices = _invoices(_invoice("S1"))
    lines = _lines({"invoice_id": "S1"}, {"invoice_id": "S9"})

    # Act
    facts = build_fact_invoice_line(lines, build_fact_invoice(invoices, lines))

    # Assert
    assert facts["invoice_id"].tolist() == ["S1"]


# The frames must fit the declared Parquet schemas, so every version's files share one schema.
@pytest.mark.parametrize(
    ("build", "schema"),
    [
        (lambda invoices, lines: build_dim_date(invoices), DIM_DATE_SCHEMA),
        (lambda invoices, lines: build_dim_product(lines, invoices), DIM_PRODUCT_SCHEMA),
        (lambda invoices, lines: build_fact_invoice(invoices, lines), FACT_INVOICE_SCHEMA),
        (lambda invoices, lines: build_fact_invoice_line(lines, build_fact_invoice(invoices, lines)), FACT_INVOICE_LINE_SCHEMA),
    ],
    ids=["dim_date", "dim_product", "fact_invoice", "fact_invoice_line"],
)
def test_gold_tables_convert_to_their_declared_schemas(build, schema):
    # Arrange
    invoices = _invoices(_invoice("S1", paid="2026-09-10"), _invoice("S2"))
    lines = _lines({"invoice_id": "S1"})

    # Act
    table = pa.Table.from_pandas(build(invoices, lines), schema=schema, preserve_index=False)

    # Assert
    assert table.schema.equals(schema)


RUN = datetime(2026, 10, 21, 14, tzinfo=UTC)


def test_name_version_sorts_by_time_down_to_the_microsecond():
    # Arrange / Act
    names = [name_version(datetime(2026, 10, 21, 14, 0, 0, micro, tzinfo=UTC)) for micro in (2, 10)]

    # Assert
    assert names == ["v=20261021T140000000002Z", "v=20261021T140000000010Z"]
    assert names == sorted(names)


def test_split_by_month_groups_facts_by_their_posting_month():
    # Arrange
    facts = pd.DataFrame({"invoice_id": ["S1", "S2", "S3"], "posting_date_key": [20260930, 20261001, 20260901]})

    # Act
    parts = split_by_month(facts)

    # Assert
    assert [(name, rows["invoice_id"].tolist()) for name, rows in parts] == [
        ("posting_month=2026-09", ["S1", "S3"]), ("posting_month=2026-10", ["S2"])
    ]


# The pointer keeps the two versions before it, so a reader that picked one of them up to two
# publications ago can still finish reading its files.
@pytest.mark.parametrize(
    ("previous", "expected"),
    [
        (None, []),
        ({"version": "v=1", "retained": []}, ["v=1"]),
        ({"version": "v=3", "retained": ["v=1", "v=2"]}, ["v=2", "v=3"]),
    ],
    ids=["first_publication", "one_before", "oldest_drops_out"],
)
def test_build_pointer_retains_the_two_previous_versions(previous, expected):
    # Arrange / Act
    pointer = build_pointer(previous, "v=4", {"dim_date": ["dim_date/v=4/all/part-00000.parquet"]}, {"dim_date": 1}, RUN)

    # Assert
    assert (pointer["version"], pointer["retained"]) == ("v=4", expected)


# Cleaning up means "delete everything not kept", not "delete the oldest": a run that crashed
# before publishing leaves files no pointer will ever name.
def test_find_unreferenced_versions_returns_old_and_never_published_versions():
    # Arrange
    stored = {"dim_date": ["v=1", "v=2", "v=3", "v=4", "v=5"], "fact_invoice": ["v=2", "v=4"]}
    pointer = {"version": "v=4", "retained": ["v=2", "v=3"]}

    # Act
    removed = find_unreferenced_versions(stored, pointer)

    # Assert
    assert removed == [("dim_date", "v=1"), ("dim_date", "v=5")]


@pytest.fixture
def lake():
    # Arrange: every test gets its own root, because fsspec's memory filesystem is one process-wide store
    root = f"memory://gold-{uuid4().hex}"
    return Lake(LakeSettings(layer_uris={layer: f"{root}/{layer}" for layer in Layer}))


def _document(key, posted, amount=100.0):
    dates = {"postingDate": posted, "documentCreateDate": posted, "documentCreateDate1": posted,
             "dueInDate": posted, "baselineCreateDate": posted, "clearDate": None}
    line = {"lineNo": 1, "sku": "LAP-DELL-7450", "productName": "Latitude 7450", "brand": "Dell",
            "category": "Laptop", "quantity": 1, "unitPrice": amount, "lineTotal": amount}
    return {"_id": key, "businessCode": "U001", "customer": {"number": "0100001196", "name": "DOLLAR llc", "nameLower": "dollar llc"},
            "currency": "USD", "documentType": "RV", "isOpen": True, "amounts": {"totalOpen": amount}, "dates": dates,
            "paymentTerms": "NAA8", "lines": [line], "updatedAt": datetime(2026, 10, 15)}


@pytest.fixture
def silver(lake):
    # Arrange: two September invoices and one from October, merged into silver
    documents = [_document("S1", datetime(2026, 9, 1)), _document("S2", datetime(2026, 9, 2)), _document("S3", datetime(2026, 10, 1))]
    lake.replace_partition(Layer.BRONZE, BRONZE_DATASET, "changed_at=2026-10-16-00", [to_table(documents, RUN)])
    merge_silver(lake)
    return lake


def test_materialize_gold_publishes_every_table_behind_the_pointer(silver):
    # Arrange / Act
    run = materialize_gold(silver, RUN)

    # Assert
    pointer = read_current(silver)
    assert pointer["version"] == run.version == "v=20261021T140000000000Z"
    assert run.rows == {"dim_date": 31, "dim_customer": 1, "dim_product": 1, "fact_invoice": 3, "fact_invoice_line": 3}
    assert [file.split("/")[2] for file in pointer["tables"]["fact_invoice"]] == ["posting_month=2026-09", "posting_month=2026-10"]
    assert read_gold_table(silver, pointer, "fact_invoice")["invoice_id"].to_pylist() == ["S1", "S2", "S3"]


def test_materialize_gold_keeps_three_versions_and_deletes_the_rest(silver):
    # Arrange
    runs = [datetime(2026, 10, 21, hour, tzinfo=UTC) for hour in (10, 11, 12)]
    for when in runs:
        materialize_gold(silver, when)

    # Act
    run = materialize_gold(silver, datetime(2026, 10, 21, 13, tzinfo=UTC))

    # Assert
    kept = [name_version(when) for when in runs[1:]] + [run.version]
    assert silver.list_partitions(Layer.GOLD, "fact_invoice") == kept
    assert run.removed == [f"{name}/{name_version(runs[0])}" for name in ("dim_date", "dim_customer", "dim_product", "fact_invoice", "fact_invoice_line")]


class CrashingLake(Lake):
    def __init__(self, settings):
        super().__init__(settings)
        self.crash = False

    def write_pointer(self, layer, name, value):
        if self.crash:
            raise OSError("connection reset while publishing")
        super().write_pointer(layer, name, value)


# A run that dies after writing its files but before the pointer must leave readers on the
# previous complete version, and the next run must sweep the orphaned files away.
def test_materialize_gold_crash_before_the_pointer_keeps_the_previous_version(silver):
    # Arrange
    crashing = CrashingLake(silver._settings)
    first = materialize_gold(crashing, datetime(2026, 10, 21, 10, tzinfo=UTC))
    crashing.crash = True
    with pytest.raises(OSError):
        materialize_gold(crashing, datetime(2026, 10, 21, 11, tzinfo=UTC))
    orphan = name_version(datetime(2026, 10, 21, 11, tzinfo=UTC))

    # Act
    pointer = read_current(crashing)
    crashing.crash = False
    later = materialize_gold(crashing, datetime(2026, 10, 21, 12, tzinfo=UTC))

    # Assert
    assert pointer["version"] == first.version
    assert read_gold_table(crashing, pointer, "fact_invoice").num_rows == 3
    assert f"fact_invoice/{orphan}" in later.removed
