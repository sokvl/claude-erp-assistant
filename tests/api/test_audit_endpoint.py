from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.auth.roles import Principal, Role
from app.db import get_database
from app.invoices.events import HISTORY_SORT, Actor, ActorType, EventType, build_event
from app.limits import MAX_INVOICE_EVENTS, MAX_TEXT_LENGTH, QUERY_TIMEOUT_MS
from app.main import app
from app.security import current_principal

ADMIN = Principal("board", Role.ADMIN)
ANNA = Actor(ActorType.USER, "anna")


class Events:
    def __init__(self, *documents):
        self.documents = list(documents)
        self.finds = []

    def find(self, criteria, **options):
        self.finds.append((criteria, options))
        return iter(document for document in self.documents if document["invoiceId"] == criteria["invoiceId"])


@pytest.fixture
def events():
    stored = Events(
        build_event("S1", EventType.CLOSE_REQUESTED, ANNA, datetime(2026, 10, 19, 9, 50, tzinfo=UTC), reason="paid by wire"),
        build_event("S1", EventType.CLOSED, ANNA, datetime(2026, 10, 19, 9, 52, tzinfo=UTC), reason="paid by wire"),
        build_event("S2", EventType.CLOSE_REJECTED, ANNA, datetime(2026, 10, 19, 10, tzinfo=UTC)),
    )
    app.dependency_overrides[get_database] = lambda: {"invoice_events": stored}
    app.dependency_overrides[current_principal] = lambda: ADMIN
    yield stored
    app.dependency_overrides.clear()


@pytest.fixture
def client(events):
    return TestClient(app)


def test_invoice_events_returns_the_invoice_history_with_who_did_what(client, events):
    # Arrange / Act
    response = client.get("/audit/invoices/S1/events")

    # Assert
    body = response.json()
    assert (response.status_code, body["invoiceId"], [event["type"] for event in body["events"]]) == (
        200, "S1", ["close_requested", "closed"]
    )
    assert body["events"][1]["actor"] == {"type": "user", "id": "anna"}
    assert ("id" in body["events"][0], "_id" in body["events"][0]) == (True, False)


def test_invoice_events_reads_in_time_order_with_a_cap_and_a_timeout(client, events):
    # Arrange / Act
    client.get("/audit/invoices/S1/events")

    # Assert
    assert events.finds == [({"invoiceId": "S1"}, {"sort": HISTORY_SORT, "limit": MAX_INVOICE_EVENTS, "max_time_ms": QUERY_TIMEOUT_MS})]


def test_invoice_events_unknown_invoice_returns_an_empty_history(client):
    # Arrange / Act
    response = client.get("/audit/invoices/S404/events")

    # Assert
    assert (response.status_code, response.json()) == (200, {"invoiceId": "S404", "events": []})


def test_invoice_events_overlong_id_returns_422_without_reading(client, events):
    # Arrange / Act
    response = client.get(f"/audit/invoices/{'x' * (MAX_TEXT_LENGTH + 1)}/events")

    # Assert
    assert (response.status_code, events.finds) == (422, [])
