from datetime import UTC, datetime, timedelta

import pytest

from app.invoices.pending_actions import (
    decide_pending_action,
    record_outcome,
    save_pending_action,
)
from app.limits import PENDING_ACTION_TTL_MINUTES, QUERY_TIMEOUT_MS

CONSEQUENCE = {
    "currentAmountOpen": 1234.5,
    "currency": "USD",
    "customerNumber": "0200769623",
    "customerName": "WAL-MART",
}


class Collection:
    def __init__(self, documents=()):
        self.documents = [dict(document) for document in documents]
        self.kwargs = []

    def insert_one(self, document):
        self.documents.append(document)

    def find_one(self, criteria, projection=None, **kwargs):
        self.kwargs.append(kwargs)
        return next((doc for doc in self.documents if _matches(criteria, doc)), None)

    def find_one_and_update(self, criteria, update, **kwargs):
        self.kwargs.append(kwargs)
        document = self.find_one(criteria)
        if document is None:
            return None
        document.update(update["$set"])
        return dict(document)

    def update_one(self, criteria, update, **kwargs):
        document = self.find_one(criteria)
        if document is not None:
            document.update(update["$set"])


def _matches(criteria, document):
    for key, expected in criteria.items():
        value = document.get(key)
        if isinstance(expected, dict):
            if "$gt" in expected and not (value is not None and value > expected["$gt"]):
                return False
        elif value != expected:
            return False
    return True


def _pending(**overrides):
    created_at = datetime.now(UTC)
    return {
        "_id": "action-1",
        "action": "close_invoice",
        "invoiceId": "1930438491",
        "reason": "wire received off-system",
        "consequence": CONSEQUENCE,
        "status": "pending",
        "conversationId": "conv-1",
        "requestedBy": "anna",
        "createdAt": created_at,
        "expiresAt": created_at + timedelta(minutes=PENDING_ACTION_TTL_MINUTES),
        "decidedAt": None,
        "decidedBy": None,
        "decidedReason": None,
    } | overrides


def test_save_pending_action_stores_an_undecided_request_under_a_new_id():
    # Arrange
    collection = Collection()

    # Act
    action_id = save_pending_action(collection, "conv-1", "anna", "1930438491", "wire received", CONSEQUENCE)

    # Assert: nothing about the invoice is touched here - only the request is recorded
    [document] = collection.documents
    assert document["_id"] == action_id
    assert (document["status"], document["decidedAt"]) == ("pending", None)
    assert (document["invoiceId"], document["reason"]) == ("1930438491", "wire received")
    assert (document["consequence"], document["conversationId"]) == (CONSEQUENCE, "conv-1")
    assert (document["requestedBy"], document["decidedBy"]) == ("anna", None)


def test_save_pending_action_always_sets_an_expiry_one_ttl_after_creation():
    # Arrange
    collection = Collection()
    before = datetime.now(UTC)

    # Act
    save_pending_action(collection, "conv-1", "anna", "1930438491", "wire received", CONSEQUENCE)

    # Assert
    [document] = collection.documents
    assert document["expiresAt"] - document["createdAt"] == timedelta(minutes=PENDING_ACTION_TTL_MINUTES)
    assert before <= document["createdAt"] <= datetime.now(UTC)


@pytest.mark.parametrize(
    ("approve", "expected"),
    [(True, "approved"), (False, "rejected")],
    ids=["approve", "reject"],
)
def test_decide_pending_action_pending_records_the_verdict_and_returns_it(approve, expected):
    # Arrange
    collection = Collection([_pending()])

    # Act
    action = decide_pending_action(collection, "action-1", "anna", approve, "checked the bank statement")

    # Assert
    assert (action["status"], action["decidedReason"], action["decidedBy"]) == (expected, "checked the bank statement", "anna")
    assert collection.documents[0]["status"] == expected
    assert action["decidedAt"] is not None


# Only the manager who asked can decide: the card is shown in their chat, and a
# request id seen elsewhere must not let another account close the invoice.
def test_decide_pending_action_other_user_returns_none_and_leaves_it_pending():
    # Arrange
    collection = Collection([_pending()])

    # Act
    action = decide_pending_action(collection, "action-1", "piotr", True, None)

    # Assert
    assert (action, collection.documents[0]["status"]) == (None, "pending")


@pytest.mark.parametrize(
    "stored",
    [_pending(status="approved"), _pending(status="rejected")],
    ids=["already_approved", "already_rejected"],
)
def test_decide_pending_action_already_decided_returns_none(stored):
    # Arrange
    collection = Collection([stored])

    # Act
    action = decide_pending_action(collection, "action-1", "anna", True, None)

    # Assert
    assert action is None


def test_decide_pending_action_unknown_id_returns_none():
    # Arrange
    collection = Collection([_pending()])

    # Act
    action = decide_pending_action(collection, "action-missing", "anna", True, None)

    # Assert
    assert action is None


def test_decide_pending_action_expired_but_not_yet_swept_returns_none():
    # Arrange
    expired = _pending(expiresAt=datetime.now(UTC) - timedelta(seconds=1))
    collection = Collection([expired])

    # Act
    action = decide_pending_action(collection, "action-1", "anna", True, None)

    # Assert
    assert (action, collection.documents[0]["status"]) == (None, "pending")


def test_record_outcome_stores_whether_the_invoice_actually_changed():
    # Arrange
    collection = Collection([_pending(status="approved")])

    # Act
    record_outcome(collection, "action-1", True)

    # Assert
    assert collection.documents[0]["invoiceClosed"] is True


def test_decide_pending_action_times_out_with_the_command_spelling():
    # Arrange: find_one_and_update forwards its kwargs into the command, so it takes maxTimeMS
    collection = Collection([_pending()])

    # Act
    decide_pending_action(collection, "action-1", "anna", True, None)

    # Assert
    assert collection.kwargs[0]["maxTimeMS"] == QUERY_TIMEOUT_MS
