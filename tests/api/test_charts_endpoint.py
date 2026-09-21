from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.config import API_KEY
from app.db import get_database
from app.limits import MAX_RECENT_CHARTS
from app.main import app

AUTH = {"X-API-Key": API_KEY}
PNG = b"\x89PNG\r\n\x1a\nfake"


def _chart(chart_id, conversation_id="conv-1"):
    return {
        "_id": chart_id,
        "conversationId": conversation_id,
        "createdAt": datetime(2020, 5, 1, tzinfo=UTC),
        "expiresAt": datetime(2020, 5, 31, tzinfo=UTC),
        "title": "Invoiced by customer",
        "chartType": "bar",
        "metric": "total",
        "groupBy": "customer",
        "image": PNG,
    }


class FakeCharts:
    def __init__(self):
        self.documents = [_chart("chart-1"), _chart("chart-2"), _chart("chart-3", "conv-2")]
        self.find_calls = []

    def find_one(self, criteria, **kwargs):
        return next((doc for doc in self.documents if doc["_id"] == criteria["_id"]), None)

    def find(self, criteria, projection, **kwargs):
        self.find_calls.append((criteria, projection, kwargs))
        matching = [doc for doc in self.documents if doc["conversationId"] == criteria["conversationId"]]
        return iter([{key: value for key, value in doc.items() if key != "image"} for doc in matching])


@pytest.fixture
def charts():
    fake = FakeCharts()
    app.dependency_overrides[get_database] = lambda: {"charts": fake}
    yield fake
    app.dependency_overrides.clear()


@pytest.fixture
def client(charts):
    return TestClient(app)


def test_getChartImage_knownId_returnsThePngBytes(client):
    # Arrange / Act
    response = client.get("/charts/chart-1/image", headers=AUTH)

    # Assert
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content == PNG


def test_getChartImage_unknownId_returns404(client):
    # Arrange / Act
    response = client.get("/charts/nope/image", headers=AUTH)

    # Assert
    assert (response.status_code, response.json()["detail"]) == (404, "Unknown chart")


# A chart id is never reused, so the browser may hold the image; "private" keeps it
# out of any shared cache, because these are internal receivables figures.
def test_getChartImage_always_isPrivatelyCacheable(client):
    # Arrange / Act
    response = client.get("/charts/chart-1/image", headers=AUTH)

    # Assert
    assert response.headers["cache-control"] == "private, max-age=86400, immutable"


def test_listRecentCharts_conversation_returnsMetadataWithoutTheImage(client):
    # Arrange / Act
    response = client.get("/charts", params={"conversation_id": "conv-1"}, headers=AUTH)

    # Assert
    items = response.json()["items"]
    assert [item["_id"] for item in items] == ["chart-1", "chart-2"]
    assert all("image" not in item for item in items)
    assert items[0]["title"] == "Invoiced by customer"


@pytest.mark.parametrize(
    ("params", "expected_status"),
    [
        ({}, 422),
        ({"conversation_id": "conv-1", "limit": 0}, 422),
        ({"conversation_id": "conv-1", "limit": MAX_RECENT_CHARTS + 1}, 422),
        ({"conversation_id": "x" * 65}, 422),
        ({"conversation_id": "conv-1", "limit": MAX_RECENT_CHARTS}, 200),
    ],
    ids=["missing_conversation", "zero_limit", "limit_over_cap", "conversation_id_too_long", "limit_at_cap"],
)
def test_listRecentCharts_parameters_areBounded(client, params, expected_status):
    # Arrange / Act
    response = client.get("/charts", params=params, headers=AUTH)

    # Assert
    assert response.status_code == expected_status


@pytest.mark.parametrize(
    "path",
    ["/charts?conversation_id=conv-1", "/charts/chart-1/image"],
    ids=["recent_list", "image"],
)
def test_charts_withoutApiKey_isRejected(client, path):
    # Arrange / Act
    response = client.get(path)

    # Assert
    assert response.status_code == 401
