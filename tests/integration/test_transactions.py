import os
from uuid import uuid4

import pytest
from pymongo.errors import DuplicateKeyError

from app.db import build_transaction_runner

pytestmark = pytest.mark.integration


@pytest.fixture
def database(mongo_client):
    # Arrange: transactions exist only on a replica set; CI starts one and requires it
    if not mongo_client.admin.command("hello").get("setName"):
        if os.environ.get("REQUIRE_MONGO"):
            pytest.fail("MongoDB is a standalone server; transactions need a replica set")
        pytest.skip("MongoDB is a standalone server; transactions need a replica set")
    name = f"test_transactions_{uuid4().hex[:8]}"
    db = mongo_client[name]
    db.create_collection("invoices")
    db.create_collection("invoice_events")
    db["invoices"].insert_one({"_id": "S1", "isOpen": True})

    yield db

    # Annihilate
    mongo_client.drop_database(name)


def _close_and_record(db, event_id):
    def callback(session):
        db["invoices"].update_one({"_id": "S1"}, {"$set": {"isOpen": False}}, session=session)
        db["invoice_events"].insert_one({"_id": event_id, "invoiceId": "S1", "type": "closed"}, session=session)

    return callback


def test_transaction_commits_every_write_together(mongo_client, database):
    # Arrange
    run = build_transaction_runner(mongo_client)

    # Act
    run(_close_and_record(database, "e1"))

    # Assert
    assert (database["invoices"].find_one({"_id": "S1"})["isOpen"], database["invoice_events"].count_documents({})) == (False, 1)


# The point of the transaction: when the event cannot be written, the invoice must not stay
# closed without a trace of who closed it.
def test_transaction_failing_second_write_undoes_the_first(mongo_client, database):
    # Arrange
    database["invoice_events"].insert_one({"_id": "e1", "invoiceId": "S1", "type": "closed"})
    run = build_transaction_runner(mongo_client)

    # Act
    with pytest.raises(DuplicateKeyError):
        run(_close_and_record(database, "e1"))

    # Assert
    assert (database["invoices"].find_one({"_id": "S1"})["isOpen"], database["invoice_events"].count_documents({})) == (True, 1)
