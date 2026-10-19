from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.auth.roles import Principal, Role
from app.db import get_database, get_transaction_runner
from app.limits import MAX_CLOSE_REASON_LENGTH
from app.main import app
from app.security import current_principal

MANAGER = Principal("anna", Role.MANAGER)


INVOICE_ID = "1930438491"


class Store:
    def __init__(self, *documents):
        self.documents = {document["_id"]: dict(document) for document in documents}

    def find_one(self, criteria, projection=None, **kwargs):
        document = self.documents.get(criteria["_id"])
        return dict(document) if document is not None and _matches(criteria, document) else None

    def find_one_and_update(self, criteria, update, **kwargs):
        if self.find_one(criteria) is None:
            return None
        document = self.documents[criteria["_id"]]
        document.update(update["$set"])
        return dict(document)

    def update_one(self, criteria, update, **kwargs):
        matched = self.find_one(criteria) is not None
        if matched:
            self.documents[criteria["_id"]].update(update["$set"])
        return SimpleNamespace(modified_count=int(matched))

    def insert_one(self, document, **kwargs):
        self.documents[document["_id"]] = dict(document)


def _matches(criteria, document):
    for key, expected in criteria.items():
        value = document.get(key)
        if isinstance(expected, dict):
            if not (value is not None and value > expected["$gt"]):
                return False
        elif value != expected:
            return False
    return True


def _pending(**overrides):
    return {
        "_id": "action-1",
        "invoiceId": INVOICE_ID,
        "reason": "wire received off-system",
        "requestedBy": "anna",
        "conversationId": "conv-1",
        "suggestedPaidOn": datetime(2026, 10, 2, tzinfo=UTC),
        "status": "pending",
        "expiresAt": datetime.now(UTC) + timedelta(minutes=5),
    } | overrides


@pytest.fixture
def db():
    stores = {
        "pending_actions": Store(_pending()),
        "invoices": Store({"_id": INVOICE_ID, "isOpen": True, "dates": {"postingDate": datetime(2026, 9, 26)}}),
        "invoice_events": Store(),
    }
    app.dependency_overrides[get_database] = lambda: stores
    app.dependency_overrides[get_transaction_runner] = lambda: lambda callback: callback(None)
    app.dependency_overrides[current_principal] = lambda: MANAGER
    yield stores
    app.dependency_overrides.clear()


@pytest.fixture
def client(db):
    return TestClient(app)


def _events(db):
    return list(db["invoice_events"].documents.values())


def test_approve_pending_action_closes_the_invoice_and_records_the_outcome(client, db):
    # Arrange / Act
    response = client.post("/pending-actions/action-1/approve", json={"reason": "bank statement checked", "paid_on": "2026-10-03"})

    # Assert
    assert (response.status_code, response.json()) == (
        200,
        {"pendingActionId": "action-1", "status": "approved", "invoiceId": INVOICE_ID, "invoiceClosed": True},
    )
    invoice = db["invoices"].documents[INVOICE_ID]
    action = db["pending_actions"].documents["action-1"]
    assert (invoice["isOpen"], invoice["dates.clearDate"], "closedReason" in invoice) == (False, datetime(2026, 10, 3, tzinfo=UTC), False)
    assert (action["invoiceClosed"], action["decidedReason"], action["decidedBy"], action["paidOn"]) == (
        True, "bank statement checked", "anna", datetime(2026, 10, 3, tzinfo=UTC)
    )


# The invoice keeps its state; who closed it, why, with which date and what the model had
# suggested go into the event log.
def test_approve_pending_action_writes_a_closed_event_with_the_full_story(client, db):
    # Arrange / Act
    client.post("/pending-actions/action-1/approve", json={"paid_on": "2026-10-03"})

    # Assert
    [event] = _events(db)
    assert {key: event[key] for key in ("invoiceId", "type", "actor", "reason", "paidOn", "suggestedPaidOn", "actionId", "conversationId")} == {
        "invoiceId": INVOICE_ID,
        "type": "closed",
        "actor": {"type": "user", "id": "anna"},
        "reason": "wire received off-system",
        "paidOn": datetime(2026, 10, 3, tzinfo=UTC),
        "suggestedPaidOn": datetime(2026, 10, 2, tzinfo=UTC),
        "actionId": "action-1",
        "conversationId": "conv-1",
    }


def test_approve_pending_action_without_a_payment_date_closes_as_a_write_off(client, db):
    # Arrange / Act
    response = client.post("/pending-actions/action-1/approve")

    # Assert
    assert response.json()["invoiceClosed"] is True
    assert (db["invoices"].documents[INVOICE_ID]["dates.clearDate"], _events(db)[0]["paidOn"]) == (None, None)


# A wrong date is refused before anything is written, so the manager fixes the field and
# clicks again instead of losing the request.
@pytest.mark.parametrize(
    ("paid_on", "detail"),
    [("2999-01-01", "is in the future"), ("2026-09-25", "before the invoice was posted on 2026-09-26")],
    ids=["future", "before_posting"],
)
def test_approve_pending_action_invalid_payment_date_returns_422_and_keeps_the_request(client, db, paid_on, detail):
    # Arrange / Act
    response = client.post("/pending-actions/action-1/approve", json={"paid_on": paid_on})

    # Assert
    assert (response.status_code, detail in response.json()["detail"]) == (422, True)
    assert (db["pending_actions"].documents["action-1"]["status"], db["invoices"].documents[INVOICE_ID]["isOpen"], _events(db)) == (
        "pending", True, []
    )


def test_reject_pending_action_leaves_the_invoice_open(client, db):
    # Arrange / Act
    response = client.post("/pending-actions/action-1/reject")

    # Assert
    assert (response.status_code, response.json()["status"], response.json()["invoiceClosed"]) == (200, "rejected", False)
    assert db["invoices"].documents[INVOICE_ID]["isOpen"] is True
    assert "invoiceClosed" not in db["pending_actions"].documents["action-1"]


def test_reject_pending_action_writes_a_close_rejected_event_with_the_managers_reason(client, db):
    # Arrange / Act
    client.post("/pending-actions/action-1/reject", json={"reason": "wrong customer"})

    # Assert
    [event] = _events(db)
    assert (event["type"], event["actor"], event["reason"], event["paidOn"]) == ("close_rejected", {"type": "user", "id": "anna"}, "wrong customer", None)


# Paid by other means between the request and the click: the approval is recorded,
# but nothing changed, and the page says so instead of claiming it closed it.
def test_approve_pending_action_invoice_already_closed_reports_invoice_closed_false(client, db):
    # Arrange
    db["invoices"].documents[INVOICE_ID]["isOpen"] = False

    # Act
    response = client.post("/pending-actions/action-1/approve")

    # Assert
    assert (response.json()["status"], response.json()["invoiceClosed"]) == ("approved", False)
    assert (db["pending_actions"].documents["action-1"]["invoiceClosed"], _events(db)) == (False, [])


@pytest.mark.parametrize(
    ("action_id", "stored"),
    [
        ("action-missing", _pending()),
        ("action-1", _pending(expiresAt=datetime.now(UTC) - timedelta(seconds=1))),
        ("action-1", _pending(status="rejected")),
        ("action-1", _pending(requestedBy="piotr")),
    ],
    ids=["unknown", "expired_but_not_yet_swept", "already_decided", "another_users_request"],
)
def test_approve_pending_action_not_decidable_returns_409_and_leaves_the_invoice_open(client, db, action_id, stored):
    # Arrange
    db["pending_actions"].documents = {stored["_id"]: stored}

    # Act
    response = client.post(f"/pending-actions/{action_id}/approve")

    # Assert
    assert response.status_code == 409
    assert db["invoices"].documents[INVOICE_ID]["isOpen"] is True


@pytest.mark.parametrize(
    "body",
    [{"reason": "x" * (MAX_CLOSE_REASON_LENGTH + 1)}, {"approve": True}],
    ids=["reason_over_cap", "unknown_field"],
)
def test_decide_pending_action_invalid_body_returns_422_and_decides_nothing(client, db, body):
    # Arrange / Act
    response = client.post("/pending-actions/action-1/approve", json=body)

    # Assert
    assert response.status_code == 422
    assert db["pending_actions"].documents["action-1"]["status"] == "pending"
