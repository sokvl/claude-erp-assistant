import os
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from indexes import INVOICE_EVENT_INDEXES, sync_indexes
from pymongo.errors import DuplicateKeyError

from app.db import build_transaction_runner
from app.invoices.closing import decide_close
from app.invoices.events import Actor, ActorType, EventType, build_event

pytestmark = pytest.mark.integration

TODAY = date(2026, 10, 19)


@pytest.fixture
def database(mongo_client):
    # Arrange: a throwaway database on a replica set, the only place transactions exist
    if not mongo_client.admin.command("hello").get("setName"):
        if os.environ.get("REQUIRE_MONGO"):
            pytest.fail("MongoDB is a standalone server; transactions need a replica set")
        pytest.skip("MongoDB is a standalone server; transactions need a replica set")
    name = f"test_close_flow_{uuid4().hex[:8]}"
    db = mongo_client[name]
    db["invoices"].insert_one({"_id": "S1", "isOpen": True, "dates": {"postingDate": datetime(2026, 9, 26), "clearDate": None}})
    db["pending_actions"].insert_one({
        "_id": "action-1", "invoiceId": "S1", "reason": "paid by wire", "requestedBy": "anna", "status": "pending",
        "conversationId": "conv-1", "expiresAt": datetime.now(UTC) + timedelta(minutes=5),
    })
    sync_indexes(db["invoice_events"], INVOICE_EVENT_INDEXES)

    yield db

    # Annihilate
    mongo_client.drop_database(name)


def _approve(mongo_client, db):
    return decide_close(
        db["pending_actions"], db["invoices"], db["invoice_events"], build_transaction_runner(mongo_client),
        "action-1", "anna", True, "bank statement checked", date(2026, 10, 3), TODAY,
    )


def test_approve_closes_the_invoice_and_logs_the_event_together(mongo_client, database):
    # Arrange / Act
    decision = _approve(mongo_client, database)

    # Assert
    invoice = database["invoices"].find_one({"_id": "S1"})
    event = database["invoice_events"].find_one({"invoiceId": "S1"})
    assert (decision.invoice_closed, invoice["isOpen"], invoice["dates"]["clearDate"]) == (True, False, datetime(2026, 10, 3))
    assert (event["type"], event["actor"], database["pending_actions"].find_one()["status"]) == (
        "closed", {"type": "user", "id": "anna"}, "approved"
    )


# The event for this request already exists, so the transaction fails on its last write: the
# invoice must still be open and the request still pending, never closed without a trace.
def test_failing_event_write_rolls_back_the_close_and_the_decision(mongo_client, database):
    # Arrange
    database["invoice_events"].insert_one(
        build_event("S1", EventType.CLOSED, Actor(ActorType.USER, "anna"), datetime(2026, 10, 19), action_id="action-1")
    )

    # Act
    with pytest.raises(DuplicateKeyError):
        _approve(mongo_client, database)

    # Assert
    assert (database["invoices"].find_one({"_id": "S1"})["isOpen"], database["pending_actions"].find_one()["status"]) == (True, "pending")
