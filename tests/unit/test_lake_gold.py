from datetime import date

import pandas as pd
import pyarrow as pa
import pytest

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
    to_date_key,
)


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
