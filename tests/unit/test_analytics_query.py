from datetime import date

import duckdb
import pytest

from app.analytics.query import build_analytics_query, read_month, select_month_files, to_date_key
from app.invoices.enums import GroupBy
from app.invoices.schemas import InvoiceAnalyticsParams

AS_OF = date(2026, 10, 21)

# S1 USD open, due before AS_OF, two lines of two brands; S2 USD paid in 9 days; S3 CAD open, due the
# day before AS_OF; S4 USD open and long overdue, posted in July.
INVOICES = """
    SELECT * FROM (VALUES
        ('S1', 'C1', 20260901, 20260916, NULL::INT, 'USD', 100.0, true, NULL::BIGINT),
        ('S2', 'C1', 20260902, 20260917, 20260911, 'USD', 50.0, false, 9::BIGINT),
        ('S3', 'C2', 20261001, 20261020, NULL::INT, 'CAD', 30.0, true, NULL::BIGINT),
        ('S4', 'C2', 20260720, 20260801, NULL::INT, 'USD', 200.0, true, NULL::BIGINT)
    ) AS t(invoice_id, customer_number, posting_date_key, due_date_key, payment_date_key, currency, amount, is_open, days_to_pay)
"""
LINES = """
    SELECT l.*, f.currency, f.customer_number, f.posting_date_key, f.due_date_key, f.payment_date_key, f.is_open, f.days_to_pay
    FROM (VALUES
        ('S1', 1, 'LAP-DELL', 2, 30.0, 60.0),
        ('S1', 2, 'NB-HP', 1, 40.0, 40.0),
        ('S2', 1, 'LAP-DELL', 1, 50.0, 50.0),
        ('S3', 1, 'NB-HP', 1, 30.0, 30.0),
        ('S4', 1, 'LAP-DELL', 4, 50.0, 200.0)
    ) AS l(invoice_id, line_no, sku, quantity, unit_price, line_total)
    JOIN invoices f USING (invoice_id)
"""
TABLES = {
    "dim_product": "SELECT * FROM (VALUES ('LAP-DELL', 'Latitude', 'Dell', 'Laptop'), ('NB-HP', 'EliteBook', 'HP', 'Laptop')) AS t(sku, product_name, brand, category)",
    "dim_customer": "SELECT * FROM (VALUES ('C1', 'DOLLAR', 2), ('C2', 'GEOR', 1)) AS t(customer_number, canonical_name, alias_count)",
    "dim_customer_alias": "SELECT * FROM (VALUES ('C1', 'DOLLAR llc', 'dollar llc'), ('C1', 'DOLLAR corp', 'dollar corp'), ('C2', 'GEOR in', 'geor in')) AS t(customer_number, name, name_lower)",
    "dim_date": """SELECT CAST(strftime(day, '%Y%m%d') AS INT) AS date_key, year(day) AS year, quarter(day) AS quarter, month(day) AS month
                   FROM (SELECT unnest(range(DATE '2026-07-01', DATE '2026-11-01', INTERVAL 1 DAY))::DATE AS day)""",
}


@pytest.fixture(scope="module")
def gold(tmp_path_factory):
    # Arrange: a tiny gold on disk, facts split by posting month like the published layout
    root = tmp_path_factory.mktemp("gold")
    connection = duckdb.connect()
    connection.execute(f"CREATE TABLE invoices AS {INVOICES}")
    connection.execute(f"CREATE TABLE lines AS {LINES}")
    files = {}
    for name, table in (("fact_invoice", "invoices"), ("fact_invoice_line", "lines")):
        files[name] = []
        for (month,) in connection.execute(f"SELECT DISTINCT posting_date_key // 100 FROM {table} ORDER BY 1").fetchall():
            folder = root / name / f"posting_month={month // 100}-{month % 100:02d}"
            folder.mkdir(parents=True)
            path = f"{folder}/part-00000.parquet"
            connection.execute(f"COPY (SELECT * FROM {table} WHERE posting_date_key // 100 = {month}) TO '{path}' (FORMAT parquet)")
            files[name].append(path)
    for name, query in TABLES.items():
        path = f"{root}/{name}.parquet"
        connection.execute(f"COPY ({query}) TO '{path}' (FORMAT parquet)")
        files[name] = [path]
    return files


def _run(files, as_of=AS_OF, **params):
    sql, values = build_analytics_query(InvoiceAnalyticsParams(**params), as_of, files)
    cursor = duckdb.connect().execute(sql, values)
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def _pick(rows, *fields):
    return [tuple(row[field] for field in fields) for row in rows]


def test_without_grouping_totals_each_currency_with_open_overdue_and_days_to_pay(gold):
    # Arrange / Act
    rows = _run(gold)

    # Assert
    assert _pick(rows, "currency", "invoice_count", "total_amount", "open_amount", "overdue_amount", "average_days_to_pay") == [
        ("CAD", 1, 30.0, 30.0, 30.0, None),
        ("USD", 3, 350.0, 300.0, 300.0, 9.0),
    ]


# A line grouping sums lines per invoice first, so an invoice with two Dell lines counts once and
# the average is per invoice, like the $group on (key, invoice) in MongoDB.
def test_brand_grouping_counts_invoices_not_lines_and_sums_line_totals(gold):
    # Arrange / Act
    rows = _run(gold, currency="USD", group_by=GroupBy.BRAND)

    # Assert
    assert _pick(rows, "key", "invoice_count", "total_amount", "average_amount", "units", "group_count") == [
        ("Dell", 3, 310.0, 103.33, 7, 2),
        ("HP", 1, 40.0, 40.0, 1, 2),
    ]


def test_product_grouping_labels_with_the_product_name_and_prices_per_unit(gold):
    # Arrange / Act
    rows = _run(gold, currency="USD", group_by=GroupBy.PRODUCT)

    # Assert
    assert _pick(rows, "key", "label", "average_unit_price") == [("LAP-DELL", "Latitude", 44.29), ("NB-HP", "EliteBook", 40.0)]


def test_customer_grouping_labels_with_the_canonical_name(gold):
    # Arrange / Act
    rows = _run(gold, currency="USD", group_by=GroupBy.CUSTOMER)

    # Assert
    assert _pick(rows, "key", "label", "total_amount") == [("C2", "GEOR", 200.0), ("C1", "DOLLAR", 150.0)]


@pytest.mark.parametrize(
    ("group_by", "keys"),
    [(GroupBy.MONTH, ["2026-07-01", "2026-09-01"]), (GroupBy.QUARTER, ["2026-07-01"]), (GroupBy.YEAR, ["2026-01-01"])],
    ids=["month", "quarter", "year"],
)
def test_period_grouping_keys_are_period_starts_in_order(gold, group_by, keys):
    # Arrange / Act
    rows = _run(gold, currency="USD", group_by=group_by)

    # Assert
    assert [row["key"] for row in rows] == keys


@pytest.mark.parametrize(
    ("customer", "expected"),
    [("dollar l", ["S1", "S2"]), ("DOLLAR CO", ["S1", "S2"]), ("C2", ["S3", "S4"]), ("GEOR in", ["S3", "S4"]), ("ACME", [])],
    ids=["alias_prefix", "case_insensitive_other_alias", "customer_number", "full_alias", "unknown"],
)
def test_customer_filter_matches_the_number_or_a_prefix_of_any_name(gold, customer, expected):
    # Arrange / Act
    rows = _run(gold, customer=customer, group_by=GroupBy.CUSTOMER)

    # Assert
    assert sum(row["invoice_count"] for row in rows) == len(expected)


# The model is an untrusted caller: its text is bound as a value and never becomes SQL.
@pytest.mark.parametrize(
    "field", ["customer", "invoice_id"], ids=["customer", "invoice_id"],
)
def test_text_from_the_model_is_bound_never_spliced_into_the_sql(gold, field):
    # Arrange
    attack = "x' OR 1=1 --"

    # Act
    sql, values = build_analytics_query(InvoiceAnalyticsParams(**{field: attack}), AS_OF, gold)
    rows = duckdb.connect().execute(sql, values).fetchall()

    # Assert
    assert attack not in sql
    assert rows == []


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"status": "open"}, {"USD": 2, "CAD": 1}),
        ({"status": "cleared"}, {"USD": 1}),
        ({"status": "overdue"}, {"USD": 2, "CAD": 1}),
        ({"invoice_id": "S2"}, {"USD": 1}),
        ({"posted_from": date(2026, 9, 2), "posted_to": date(2026, 10, 31)}, {"USD": 1, "CAD": 1}),
        ({"min_amount": 60, "max_amount": 150}, {"USD": 1}),
    ],
    ids=["open", "cleared", "overdue", "invoice_id", "posting_range", "amount_range"],
)
def test_filters_select_invoices(gold, params, expected):
    # Arrange / Act
    rows = _run(gold, **params)

    # Assert
    assert {row["currency"]: row["invoice_count"] for row in rows} == expected


def test_overdue_depends_on_as_of_midnight(gold):
    # Arrange / Act
    rows = _run(gold, as_of=date(2026, 10, 20), status="overdue")

    # Assert
    assert {row["currency"]: row["invoice_count"] for row in rows} == {"USD": 2}


# The amount range is about the invoice, so a line grouping filters through the invoice's amount,
# not the line's: S1 (100) and S4 (200) qualify, not the 60 Dell line on its own.
def test_amount_range_on_a_line_grouping_filters_whole_invoices(gold):
    # Arrange / Act
    rows = _run(gold, currency="USD", group_by=GroupBy.BRAND, min_amount=100)

    # Assert
    assert _pick(rows, "key", "total_amount") == [("Dell", 260.0), ("HP", 40.0)]


def test_limit_cuts_rows_but_group_count_tells_how_many_there_were(gold):
    # Arrange / Act
    rows = _run(gold, currency="USD", group_by=GroupBy.BRAND, limit=1)

    # Assert
    assert _pick(rows, "key", "group_count") == [("Dell", 2)]


def test_build_analytics_query_binds_only_the_tables_it_reads(gold):
    # Arrange / Act
    _, values = build_analytics_query(InvoiceAnalyticsParams(group_by=GroupBy.BRAND), AS_OF, gold)

    # Assert
    assert {name for name in values if name.startswith(("fact_", "dim_"))} == {"fact_invoice_line", "dim_product"}


def test_build_analytics_query_rejects_a_raw_string_for_group_by():
    # Arrange
    params = InvoiceAnalyticsParams.model_construct(group_by="brand; DROP TABLE x", limit=None)

    # Act / Assert
    with pytest.raises(ValueError):
        build_analytics_query(params, AS_OF, {})


@pytest.mark.parametrize(
    ("posted_from", "posted_to", "expected"),
    [
        (None, None, ["a/posting_month=2026-07/p", "a/posting_month=2026-09/p", "a/posting_month=2026-10/p", "a/all/p"]),
        (date(2026, 9, 15), None, ["a/posting_month=2026-09/p", "a/posting_month=2026-10/p", "a/all/p"]),
        (None, date(2026, 9, 1), ["a/posting_month=2026-07/p", "a/posting_month=2026-09/p", "a/all/p"]),
    ],
    ids=["no_dates", "from_mid_month", "to_month_start"],
)
def test_select_month_files_keeps_months_in_range_and_never_drops_an_unmarked_file(posted_from, posted_to, expected):
    # Arrange
    files = ["a/posting_month=2026-07/p", "a/posting_month=2026-09/p", "a/posting_month=2026-10/p", "a/all/p"]

    # Act
    selected = select_month_files(files, posted_from, posted_to)

    # Assert
    assert selected == expected


def test_read_month_and_date_key_formats():
    # Arrange / Act / Assert
    assert (read_month("x/posting_month=2026-09/part-00000.parquet"), read_month("x/all/p")) == ("2026-09", None)
    assert to_date_key(date(2026, 1, 5)) == 20260105
