from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.auth.roles import Principal, Role
from app.db import get_database
from app.limits import MAX_CLOSE_REASON_LENGTH
from app.main import app
from app.security import current_principal

MANAGER = Principal("anna", Role.MANAGER)


INVOICE_ID = "1930438491"


class Store:
    def __init__(self, *documents):
        self.documents = {document["_id"]: dict(document) for document in documents}

    def find_one_and_update(self, criteria, update, **kwargs):
        document = self.documents.get(criteria["_id"])
        if document is None or document["status"] != criteria["status"]:
            return None
        if document["requestedBy"] != criteria["requestedBy"]:
            return None
        if document["expiresAt"] <= criteria["expiresAt"]["$gt"]:
            return None
        document.update(update["$set"])
        return dict(document)

    def update_one(self, criteria, update, **kwargs):
        document = self.documents.get(criteria["_id"])
        matched = document is not None and all(document.get(key) == value for key, value in criteria.items())
        if matched:
            document.update(update["$set"])
        return SimpleNamespace(modified_count=int(matched))


def _pending(**overrides):
    return {
        "_id": "action-1",
        "invoiceId": INVOICE_ID,
        "reason": "wire received off-system",
        "requestedBy": "anna",
        "status": "pending",
        "expiresAt": datetime.now(UTC) + timedelta(minutes=5),
    } | overrides


@pytest.fixture
def db():
    stores = {
        "pending_actions": Store(_pending()),
        "invoices": Store({"_id": INVOICE_ID, "isOpen": True}),
    }
    app.dependency_overrides[get_database] = lambda: stores
    app.dependency_overrides[current_principal] = lambda: MANAGER
    yield stores
    app.dependency_overrides.clear()


@pytest.fixture
def client(db):
    return TestClient(app)


def test_approve_pending_action_closes_the_invoice_and_records_the_outcome(client, db):
    # Arrange / Act
    response = client.post("/pending-actions/action-1/approve", json={"reason": "bank statement checked"})

    # Assert
    assert (response.status_code, response.json()) == (
        200,
        {"pendingActionId": "action-1", "status": "approved", "invoiceId": INVOICE_ID, "invoiceClosed": True},
    )
    invoice = db["invoices"].documents[INVOICE_ID]
    action = db["pending_actions"].documents["action-1"]
    assert (invoice["isOpen"], invoice["closedReason"]) == (False, "wire received off-system")
    assert (action["invoiceClosed"], action["decidedReason"], action["decidedBy"]) == (True, "bank statement checked", "anna")


def test_reject_pending_action_leaves_the_invoice_open(client, db):
    # Arrange / Act
    response = client.post("/pending-actions/action-1/reject")

    # Assert
    assert (response.status_code, response.json()["status"], response.json()["invoiceClosed"]) == (200, "rejected", False)
    assert db["invoices"].documents[INVOICE_ID]["isOpen"] is True
    assert "invoiceClosed" not in db["pending_actions"].documents["action-1"]


# Paid by other means between the request and the click: the approval is recorded,
# but nothing changed, and the page says so instead of claiming it closed it.
def test_approve_pending_action_invoice_already_closed_reports_invoice_closed_false(client, db):
    # Arrange
    db["invoices"].documents[INVOICE_ID]["isOpen"] = False

    # Act
    response = client.post("/pending-actions/action-1/approve")

    # Assert
    assert (response.json()["status"], response.json()["invoiceClosed"]) == ("approved", False)
    assert db["pending_actions"].documents["action-1"]["invoiceClosed"] is False


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
