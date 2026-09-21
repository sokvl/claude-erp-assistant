import json
from datetime import date, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from indexes import INVOICE_INDEXES, sync_indexes

from app.assistant.dispatch import run_tool
from app.config import API_KEY
from app.db import get_database
from app.invoices.schemas import InvoiceAnalyticsParams, InvoiceListParams
from app.invoices.service import analyze_invoices, list_invoices
from app.main import app

pytestmark = pytest.mark.integration

AS_OF = date(2020, 5, 31)


def _invoice(invoice_id, number, name, currency, total, posted, due, cleared=None):
    return {
        "_id": invoice_id,
        "invoiceId": invoice_id,
        "customer": {"number": number, "name": name, "nameLower": name.lower()},
        "currency": currency,
        "amounts": {"totalOpen": total},
        "isOpen": cleared is None,
        "dates": {"postingDate": posted, "dueInDate": due, "clearDate": cleared},
        "lines": LINES[invoice_id],
    }


def _line(line_no, sku, name, brand, category, quantity, unit_price):
    return {
        "lineNo": line_no, "sku": sku, "productName": name, "brand": brand, "category": category,
        "quantity": quantity, "unitPrice": unit_price, "lineTotal": quantity * unit_price,
    }


# Lines add up to their invoice totals. U3 has two GPU lines, so it must count as one GPU invoice.
LINES = {
    "U1": [_line(1, "GPU-A", "GPU A", "NVIDIA", "GPU", 2, 400.0), _line(2, "RAM-B", "RAM B", "Corsair", "RAM", 4, 50.0)],
    "U2": [_line(1, "GPU-A", "GPU A", "NVIDIA", "GPU", 1, 500.0)],
    "U3": [_line(1, "GPU-A", "GPU A", "NVIDIA", "GPU", 2, 400.0), _line(2, "GPU-D", "GPU D", "NVIDIA", "GPU", 3, 400.0)],
    "U4": [_line(1, "RAM-B", "RAM B", "Corsair", "RAM", 6, 50.0)],
    "U5": [_line(1, "CPU-C", "CPU C", "AMD", "CPU", 3, 250.0)],
    "C1": [_line(1, "GPU-A", "GPU A", "NVIDIA", "GPU", 8, 500.0)],
    "C2": [_line(1, "RAM-B", "RAM B", "Corsair", "RAM", 20, 50.0)],
}


# Paid after 30, 20 and 10 days: U1, U3, U5. U2 and C1 are overdue on AS_OF; C2 falls due exactly on AS_OF,
# so it is open but not overdue yet. Customer 0001 appears under two name spellings.
INVOICES = [
    _invoice("U1", "0001", "ACME corp", "USD", 1000.0, datetime(2020, 1, 10), datetime(2020, 2, 10), datetime(2020, 2, 9)),
    _invoice("U2", "0001", "ACME inc", "USD", 500.0, datetime(2020, 2, 15), datetime(2020, 3, 15)),
    _invoice("U3", "0002", "Globex llc", "USD", 2000.0, datetime(2020, 4, 1), datetime(2020, 5, 1), datetime(2020, 4, 21)),
    _invoice("U4", "0002", "Globex llc", "USD", 300.0, datetime(2020, 5, 20), datetime(2020, 6, 19)),
    _invoice("U5", "0003", "Initech", "USD", 750.0, datetime(2019, 12, 31), datetime(2020, 1, 30), datetime(2020, 1, 10)),
    _invoice("C1", "0100", "Maple ltd", "CAD", 4000.0, datetime(2020, 3, 3), datetime(2020, 4, 2)),
    _invoice("C2", "0100", "Maple ltd", "CAD", 1000.0, datetime(2020, 3, 20), datetime(2020, 5, 31)),
]


def _row(invoice_count, total, average, open_amount, overdue, days_to_pay, **extra):
    return {
        **({"key": extra.pop("key")} if "key" in extra else {}),
        **({"label": extra.pop("label")} if "label" in extra else {}),
        "invoiceCount": invoice_count,
        "totalAmount": total,
        "averageAmount": average,
        "openAmount": open_amount,
        "overdueAmount": overdue,
        "averageDaysToPay": days_to_pay,
        **extra,
    }


@pytest.fixture(scope="module")
def invoices(mongo_client):
    # Arrange: a throwaway database, never the demo data in invoices_db
    db_name = f"test_invoices_{uuid4().hex[:8]}"
    database = mongo_client[db_name]
    database["invoices"].insert_many(INVOICES)
    sync_indexes(database["invoices"], INVOICE_INDEXES)

    yield database["invoices"]

    # Annihilate
    mongo_client.drop_database(db_name)


def _analyze(collection, **kwargs):
    return analyze_invoices(collection, InvoiceAnalyticsParams(as_of=AS_OF, **kwargs))


def _currencies(result):
    return {entry["currency"]: (entry["groupCount"], entry["rows"]) for entry in result["currencies"]}


def test_analyze_invoices_totals_are_kept_per_currency(invoices):
    # Arrange / Act
    result = _analyze(invoices)

    # Assert
    assert (result["coverage"], _currencies(result)) == (
        {"firstPostingDate": "2019-12-31", "lastPostingDate": "2020-05-20"},
        {
            "CAD": (1, [_row(2, 5000.0, 2500.0, 5000.0, 4000.0, None)]),
            "USD": (1, [_row(5, 4550.0, 910.0, 800.0, 500.0, 20.0)]),
        },
    )


def test_analyze_invoices_customer_ranking_groups_by_number_within_each_currency(invoices):
    # Arrange / Act
    result = _analyze(invoices, group_by="customer", limit=2)

    # Assert
    assert _currencies(result) == {
        "CAD": (1, [_row(2, 5000.0, 2500.0, 5000.0, 4000.0, None, key="0100", label="Maple ltd")]),
        "USD": (3, [
            _row(2, 2300.0, 1150.0, 300.0, 0, 20.0, key="0002", label="Globex llc"),
            _row(2, 1500.0, 750.0, 500.0, 500.0, 30.0, key="0001", label="ACME inc"),
        ]),
    }


def test_analyze_invoices_category_counts_invoices_not_lines(invoices):
    # Arrange / Act
    result = _analyze(invoices, group_by="category")

    # Assert
    assert _currencies(result) == {
        "CAD": (2, [
            _row(1, 4000.0, 4000.0, 4000.0, 4000.0, None, key="GPU", units=8),
            _row(1, 1000.0, 1000.0, 1000.0, 0, None, key="RAM", units=20),
        ]),
        "USD": (3, [
            _row(3, 3300.0, 1100.0, 500.0, 500.0, 25.0, key="GPU", units=8),
            _row(1, 750.0, 750.0, 0, 0, 10.0, key="CPU", units=3),
            _row(2, 500.0, 250.0, 300.0, 0, 30.0, key="RAM", units=10),
        ]),
    }


def test_analyze_invoices_product_rows_carry_units_and_average_unit_price(invoices):
    # Arrange / Act
    result = _analyze(invoices, group_by="product", currency="USD")

    # Assert
    assert _currencies(result) == {
        "USD": (4, [
            _row(3, 2100.0, 700.0, 500.0, 500.0, 25.0, key="GPU-A", label="GPU A", units=5, averageUnitPrice=420.0),
            _row(1, 1200.0, 1200.0, 0, 0, 20.0, key="GPU-D", label="GPU D", units=3, averageUnitPrice=400.0),
            _row(1, 750.0, 750.0, 0, 0, 10.0, key="CPU-C", label="CPU C", units=3, averageUnitPrice=250.0),
            _row(2, 500.0, 250.0, 300.0, 0, 30.0, key="RAM-B", label="RAM B", units=10, averageUnitPrice=50.0),
        ]),
    }


def test_analyze_invoices_quarter_trend_is_chronological(invoices):
    # Arrange / Act
    result = _analyze(invoices, group_by="quarter", currency="USD")

    # Assert
    assert _currencies(result) == {
        "USD": (3, [
            _row(1, 750.0, 750.0, 0, 0, 10.0, key="2019-10-01"),
            _row(2, 1500.0, 750.0, 500.0, 500.0, 30.0, key="2020-01-01"),
            _row(2, 2300.0, 1150.0, 300.0, 0, 20.0, key="2020-04-01"),
        ]),
    }


@pytest.mark.parametrize(
    ("filters", "expected"),
    [
        ({"posted_from": date(2020, 1, 1), "posted_to": date(2020, 3, 31), "currency": "USD"},
         {"USD": (1, [_row(2, 1500.0, 750.0, 500.0, 500.0, 30.0)])}),
        ({"posted_from": date(2026, 1, 1)}, {}),
        ({"status": "overdue"},
         {"CAD": (1, [_row(1, 4000.0, 4000.0, 4000.0, 4000.0, None)]),
          "USD": (1, [_row(1, 500.0, 500.0, 500.0, 500.0, None)])}),
    ],
    ids=["q1_2020_usd", "period_without_data", "overdue_only"],
)
def test_analyze_invoices_filters_narrow_the_figures(invoices, filters, expected):
    # Arrange / Act
    result = _analyze(invoices, **filters)

    # Assert
    assert _currencies(result) == expected


@pytest.mark.parametrize(
    ("kwargs", "expected_ids", "expected_total"),
    [
        ({"posted_from": date(2020, 1, 10), "posted_to": date(2020, 2, 15)}, ["U2", "U1"], 2),
        ({"status": "overdue", "as_of": AS_OF}, ["C1", "U2"], 2),
        ({"status": "open", "currency": "CAD", "sort_order": "asc"}, ["C1", "C2"], 2),
        ({"customer": "acme"}, ["U2", "U1"], 2),
        ({"customer": "ACME I"}, ["U2"], 1),
        # names are matched from their beginning, which the nameLower index can bound; every customer's name
        # variants in the data share their first word, so a name beginning finds all of them
        ({"customer": "corp"}, [], 0),
        ({"customer": "0002"}, ["U4", "U3"], 2),
        ({"customer": "."}, [], 0),
        ({"min_amount": 1000}, ["U3", "C2", "C1", "U1"], 4),
        ({"sort_by": "amount", "page_size": 2}, ["C1", "U3"], 7),
        ({"sort_by": "amount", "page_size": 2, "page": 4}, ["U4"], 7),
    ],
    ids=["date_range_inclusive", "overdue", "open_cad_oldest_first", "customer_name_any_case",
         "customer_name_prefix_narrows", "customer_mid_name_fragment_does_not_match", "customer_number",
         "regex_metacharacter_is_literal", "min_amount_inclusive", "largest_first", "last_partial_page"],
)
def test_list_invoices_filters_sorts_and_pages(invoices, kwargs, expected_ids, expected_total):
    # Arrange / Act
    result = list_invoices(invoices, InvoiceListParams(**kwargs))

    # Assert
    assert ([item["invoiceId"] for item in result["items"]], result["total"]) == (expected_ids, expected_total)


def test_run_tool_analyze_invoices_returns_the_controllers_figures(invoices):
    # Arrange
    tool_input = {"group_by": "customer", "posted_from": "2020-01-01", "as_of": "2020-05-31"}
    direct = _analyze(invoices, group_by="customer", posted_from=date(2020, 1, 1))

    # Act
    result = json.loads(run_tool(invoices.database, "analyze_invoices", tool_input).content)

    # Assert
    assert result == json.loads(json.dumps(direct))


@pytest.fixture
def client(invoices):
    app.dependency_overrides[get_database] = lambda: invoices.database
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_invoice_analytics_endpoint_returns_the_controllers_figures(invoices, client):
    # Arrange
    direct = _analyze(invoices, group_by="category")

    # Act
    body = client.get("/invoices/analytics?group_by=category&as_of=2020-05-31", headers={"X-API-Key": API_KEY}).json()

    # Assert
    assert body == json.loads(json.dumps(direct))
