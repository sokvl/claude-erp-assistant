from datetime import date, datetime

import pytest

from app.invoices import service
from app.invoices.schemas import InvoiceAnalyticsParams, InvoiceListParams
from app.invoices.service import analyze_invoices, list_invoices
from app.limits import QUERY_TIMEOUT_MS

CURRENCIES = [{"currency": "USD", "groupCount": 1, "rows": [{"invoiceCount": 2, "totalAmount": 30.0}]}]


class FakeInvoices:
    def __init__(self, result, edges=(datetime(2018, 12, 30), datetime(2020, 5, 22)), total=0):
        self.result = result
        self.edges = edges
        self.total = total
        self.pipelines = []
        self.options = []
        self.find_one_calls = []
        self.finds = []
        self.counts = []

    def aggregate(self, pipeline, **kwargs):
        self.pipelines.append(pipeline)
        self.options.append(kwargs)
        return iter(self.result)

    def find(self, **kwargs):
        self.finds.append(kwargs)
        return iter(self.result)

    def count_documents(self, criteria, **kwargs):
        self.counts.append((criteria, kwargs))
        return self.total

    def find_one(self, criteria, projection, **kwargs):
        self.find_one_calls.append(kwargs)
        if not self.edges:
            return None
        oldest, newest = self.edges
        return {"dates": {"postingDate": oldest if kwargs["sort"] == [("dates.postingDate", 1)] else newest}}


@pytest.mark.parametrize(
    ("documents", "total"),
    [([{"invoiceId": "1"}], 6), ([], 5), ([], 0)],
    ids=["page_with_items", "page_past_the_end", "no_matches"],
)
def test_list_invoices_returns_the_page_with_the_filtered_total(documents, total):
    # Arrange
    collection = FakeInvoices(documents, total=total)

    # Act
    result = list_invoices(collection, InvoiceListParams(page=2, page_size=5))

    # Assert
    assert result == {"page": 2, "pageSize": 5, "total": total, "items": documents}


def test_list_invoices_page_and_count_share_the_filters_and_query_timeout():
    # Arrange
    collection = FakeInvoices([])

    # Act
    list_invoices(collection, InvoiceListParams(currency="USD", status="open"))

    # Assert
    assert (
        [(call["filter"], call["max_time_ms"]) for call in collection.finds],
        collection.counts,
    ) == (
        [({"currency": "USD", "isOpen": True}, QUERY_TIMEOUT_MS)],
        [({"currency": "USD", "isOpen": True}, {"maxTimeMS": QUERY_TIMEOUT_MS})],
    )


def test_analyze_invoices_returns_currencies_with_as_of_and_coverage():
    # Arrange
    collection = FakeInvoices(CURRENCIES)

    # Act
    result = analyze_invoices(collection, InvoiceAnalyticsParams(group_by="customer", as_of=date(2020, 5, 31)))

    # Assert
    assert result == {
        "asOf": "2020-05-31",
        "groupBy": "customer",
        "filters": {},
        "coverage": {"firstPostingDate": "2018-12-30", "lastPostingDate": "2020-05-22"},
        "currencies": CURRENCIES,
    }


def test_analyze_invoices_echoes_exactly_the_filters_it_applied():
    # Arrange: the model states the period from this echo, not from what it meant to ask
    collection = FakeInvoices(CURRENCIES)
    params = InvoiceAnalyticsParams(
        posted_from=date(2020, 1, 1), posted_to=date(2020, 3, 31), currency="USD", status="open",
        group_by="customer", limit=5, as_of=date(2020, 5, 31),
    )

    # Act
    result = analyze_invoices(collection, params)

    # Assert
    assert result["filters"] == {"posted_from": "2020-01-01", "posted_to": "2020-03-31", "currency": "USD", "status": "open"}


def test_analyze_invoices_no_match_still_reports_what_the_data_covers():
    # Arrange: "last quarter" in 2026 matches nothing; coverage lets the assistant say which dates exist
    collection = FakeInvoices([])

    # Act
    result = analyze_invoices(collection, InvoiceAnalyticsParams(posted_from=date(2026, 1, 1)))

    # Assert
    assert (result["currencies"], result["coverage"]) == (
        [],
        {"firstPostingDate": "2018-12-30", "lastPostingDate": "2020-05-22"},
    )


def test_analyze_invoices_empty_collection_has_no_coverage():
    # Arrange
    collection = FakeInvoices([], edges=())

    # Act
    result = analyze_invoices(collection, InvoiceAnalyticsParams())

    # Assert
    assert result["coverage"] == {"firstPostingDate": None, "lastPostingDate": None}


def test_analyze_invoices_every_query_has_a_timeout():
    # Arrange
    collection = FakeInvoices([])

    # Act
    analyze_invoices(collection, InvoiceAnalyticsParams())

    # Assert
    assert (collection.options, [call["max_time_ms"] for call in collection.find_one_calls]) == (
        [{"maxTimeMS": QUERY_TIMEOUT_MS}],
        [QUERY_TIMEOUT_MS, QUERY_TIMEOUT_MS],
    )


@pytest.mark.parametrize(
    ("call", "params", "criteria_of"),
    [
        (analyze_invoices, InvoiceAnalyticsParams(status="overdue"), lambda c: c.pipelines[0][0]["$match"]),
        (list_invoices, InvoiceListParams(status="overdue"), lambda c: c.finds[0]["filter"]),
    ],
    ids=["analyze", "list"],
)
def test_invoice_service_as_of_defaults_to_today(monkeypatch, call, params, criteria_of):
    # Arrange
    monkeypatch.setattr(service, "date", type("FixedDate", (), {"today": staticmethod(lambda: date(2026, 9, 18))}))
    collection = FakeInvoices([])

    # Act
    call(collection, params)

    # Assert
    assert criteria_of(collection)["dates.dueInDate"] == {"$lt": datetime(2026, 9, 18)}
