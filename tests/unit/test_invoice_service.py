from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from app.invoices import service
from app.invoices.schemas import InvoiceAnalyticsParams, InvoiceListParams
from app.invoices.service import analyze_invoices, check_paid_on, close_invoice, list_invoices, read_posting_date
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
    monkeypatch.setattr(service, "today_in_business_timezone", lambda: date(2026, 9, 18))
    collection = FakeInvoices([])

    # Act
    call(collection, params)

    # Assert
    assert criteria_of(collection)["dates.dueInDate"] == {"$lt": datetime(2026, 9, 18)}


class InvoiceStore:
    def __init__(self, *documents):
        self.documents = {document["_id"]: dict(document) for document in documents}
        self.sessions = []

    def update_one(self, criteria, update, session=None):
        self.sessions.append(session)
        document = self.documents.get(criteria["_id"])
        matched = document is not None and document["isOpen"] == criteria["isOpen"]
        if matched:
            document.update(update["$set"])
        return SimpleNamespace(modified_count=int(matched))

    def find_one(self, criteria, projection=None, **options):
        return self.documents.get(criteria["_id"])


# isOpen: True is part of the filter, so approving twice, or approving an invoice that
# got paid meanwhile, changes nothing and keeps the first closedAt.
@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        ({"_id": "1930438491", "isOpen": True}, (True, True)),
        ({"_id": "1930438491", "isOpen": False, "closedAt": "earlier"}, (False, False)),
    ],
    ids=["open_invoice", "already_closed"],
)
def test_close_invoice_closes_only_an_open_invoice(stored, expected):
    # Arrange
    collection = InvoiceStore(stored)

    # Act
    closed = close_invoice(collection, "1930438491", date(2026, 10, 3))

    # Assert
    document = collection.documents["1930438491"]
    assert (closed, document["closedAt"] != "earlier") == expected
    assert document["isOpen"] is False


# The invoice keeps only its state: who closed it and why live in the event log.
@pytest.mark.parametrize(
    ("paid_on", "clear_date"),
    [(date(2026, 10, 3), datetime(2026, 10, 3, tzinfo=UTC)), (None, None)],
    ids=["payment_received", "written_off"],
)
def test_close_invoice_records_the_payment_date_and_no_reason(paid_on, clear_date):
    # Arrange
    collection = InvoiceStore({"_id": "1930438491", "isOpen": True})

    # Act
    close_invoice(collection, "1930438491", paid_on)

    # Assert
    document = collection.documents["1930438491"]
    assert (document["dates.clearDate"], "closedReason" in document) == (clear_date, False)


def test_close_invoice_stamps_updated_at_with_the_close_time():
    # Arrange
    collection = InvoiceStore({"_id": "1930438491", "isOpen": True})

    # Act
    close_invoice(collection, "1930438491", None)

    # Assert
    document = collection.documents["1930438491"]
    assert document["updatedAt"] == document["closedAt"]


# The lake reads "what changed since last time" from updatedAt, so a refused close must not
# look like a change.
def test_close_invoice_already_closed_leaves_updated_at_alone():
    # Arrange
    collection = InvoiceStore({"_id": "1930438491", "isOpen": False, "updatedAt": "earlier"})

    # Act
    close_invoice(collection, "1930438491", None)

    # Assert
    assert collection.documents["1930438491"]["updatedAt"] == "earlier"


def test_close_invoice_unknown_id_reports_nothing_closed():
    # Arrange
    collection = InvoiceStore()

    # Act
    closed = close_invoice(collection, "404", None)

    # Assert
    assert closed is False


def test_close_invoice_writes_in_the_given_session():
    # Arrange
    collection = InvoiceStore({"_id": "1930438491", "isOpen": True})
    session = object()

    # Act
    close_invoice(collection, "1930438491", None, session)

    # Assert
    assert collection.sessions == [session]


@pytest.mark.parametrize(
    ("paid_on", "posting_date", "expected"),
    [
        (None, date(2026, 9, 26), None),
        (date(2026, 10, 3), date(2026, 9, 26), None),
        (date(2026, 9, 26), date(2026, 9, 26), None),
        (date(2026, 10, 19), date(2026, 9, 26), None),
        (date(2026, 10, 20), date(2026, 9, 26), "The payment date 2026-10-20 is in the future"),
        (date(2026, 9, 25), date(2026, 9, 26), "The payment date 2026-09-25 is before the invoice was posted on 2026-09-26"),
        (date(2026, 10, 3), None, None),
    ],
    ids=["written_off", "between_posting_and_today", "on_the_posting_day", "today", "tomorrow", "before_posting", "invoice_not_found"],
)
def test_check_paid_on_accepts_only_dates_from_posting_to_today(paid_on, posting_date, expected):
    # Arrange / Act / Assert
    assert check_paid_on(paid_on, posting_date, date(2026, 10, 19)) == expected


@pytest.mark.parametrize(
    ("stored", "expected"),
    [({"_id": "S1", "isOpen": True, "dates": {"postingDate": datetime(2026, 9, 26)}}, date(2026, 9, 26)), (None, None)],
    ids=["found", "missing"],
)
def test_read_posting_date_returns_the_day_the_invoice_was_posted(stored, expected):
    # Arrange
    collection = InvoiceStore(*([stored] if stored else []))

    # Act / Assert
    assert read_posting_date(collection, "S1") == expected
