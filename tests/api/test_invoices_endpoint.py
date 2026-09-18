from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.config import API_KEY
from app.db import get_database
from app.main import app

AUTH = {"X-API-Key": API_KEY}
ROWS = [{"currency": "USD", "groupCount": 1, "rows": [{"key": "0200769623", "totalAmount": 30.0}]}]


class FakeInvoices:
    def __init__(self):
        self.aggregate_calls = []

    def aggregate(self, pipeline, **kwargs):
        self.aggregate_calls.append(pipeline)
        if "$facet" in pipeline[2]:
            return iter([{"items": [{"invoiceId": "1930438491", "dates": {"postingDate": datetime(2020, 1, 26)}}],
                          "total": 1}])
        return iter(ROWS)

    def find_one(self, *args, **kwargs):
        return {"dates": {"postingDate": datetime(2019, 1, 2)}}


@pytest.fixture
def invoices():
    fake = FakeInvoices()
    app.dependency_overrides[get_database] = lambda: {"invoices": fake}
    yield fake
    app.dependency_overrides.clear()


@pytest.fixture
def client(invoices):
    return TestClient(app)


def test_list_invoices_query_params_reach_the_pipeline(client, invoices):
    # Arrange
    query = "?posted_from=2020-01-01&posted_to=2020-01-31&currency=USD&status=open&sort_by=amount&sort_order=asc" \
            "&page=2&page_size=5"

    # Act
    body = client.get(f"/invoices{query}", headers=AUTH).json()

    # Assert
    [pipeline] = invoices.aggregate_calls
    assert (pipeline[0], pipeline[1], pipeline[2]["$facet"]["items"][:2], body["total"]) == (
        {"$match": {
            "dates.postingDate": {"$gte": datetime(2020, 1, 1), "$lte": datetime(2020, 1, 31, 23, 59, 59, 999999)},
            "currency": "USD",
            "isOpen": True,
        }},
        {"$sort": {"amounts.totalOpen": 1, "_id": 1}},
        [{"$skip": 5}, {"$limit": 5}],
        1,
    )


def test_list_invoices_returns_iso_dates(client):
    # Arrange / Act
    body = client.get("/invoices", headers=AUTH).json()

    # Assert
    assert body["items"][0]["dates"]["postingDate"] == "2020-01-26T00:00:00"


def test_invoice_analytics_returns_figures_per_currency_with_as_of_and_coverage(client):
    # Arrange / Act
    body = client.get("/invoices/analytics?group_by=customer&limit=5&as_of=2020-05-31", headers=AUTH).json()

    # Assert
    assert body == {
        "asOf": "2020-05-31",
        "groupBy": "customer",
        "filters": {},
        "coverage": {"firstPostingDate": "2019-01-02", "lastPostingDate": "2019-01-02"},
        "currencies": ROWS,
    }


@pytest.mark.parametrize(
    "path",
    [
        # each rule is test_invoice_schemas' job; these prove both query models are wired, validators included
        "/invoices?posted_from=2020-02-01&posted_to=2020-01-01",
        "/invoices?posted_from=yesterday",
        "/invoices?region=EU",
        "/invoices/analytics?group_by=week",
        "/invoices/analytics?page=2",
    ],
    ids=["list_inverted_dates", "list_relative_date_text", "list_unknown_filter", "analytics_unknown_group_by",
         "analytics_has_no_paging"],
)
def test_invoice_endpoints_invalid_query_returns_422_without_querying(client, invoices, path):
    # Arrange / Act
    response = client.get(path, headers=AUTH)

    # Assert
    assert (response.status_code, invoices.aggregate_calls) == (422, [])

