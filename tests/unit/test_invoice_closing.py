from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.invoices.closing import CloseDecisionError, DecisionProblem, decide_close

TODAY = date(2026, 10, 19)


class Store:
    def __init__(self, *documents, decided_meanwhile=False):
        self.documents = {document["_id"]: dict(document) for document in documents}
        self.decided_meanwhile = decided_meanwhile

    def find_one(self, criteria, projection=None, **kwargs):
        return self.documents.get(criteria["_id"])

    def find_one_and_update(self, criteria, update, **kwargs):
        if self.decided_meanwhile:
            return None
        document = self.documents[criteria["_id"]]
        document.update(update["$set"])
        return dict(document)

    def update_one(self, criteria, update, **kwargs):
        self.documents[criteria["_id"]].update(update["$set"])
        return SimpleNamespace(modified_count=1)

    def insert_one(self, document, **kwargs):
        self.documents[document["_id"]] = document


def _stores(decided_meanwhile=False):
    pending = Store(
        {"_id": "action-1", "invoiceId": "S1", "reason": "paid by wire", "requestedBy": "anna", "status": "pending",
         "expiresAt": datetime.now(UTC) + timedelta(minutes=5)},
        decided_meanwhile=decided_meanwhile,
    )
    invoices = Store({"_id": "S1", "isOpen": True, "dates": {"postingDate": datetime(2026, 9, 26)}})
    return pending, invoices, Store()


def _decide(pending, invoices, events, run=lambda callback: callback(None)):
    return decide_close(pending, invoices, events, run, "action-1", "anna", True, None, date(2026, 10, 3), TODAY)


# A second click in another tab can decide the request between the preview and the
# transaction; the transaction must then write nothing and report it as not decidable.
def test_decide_close_request_decided_meanwhile_writes_nothing():
    # Arrange
    pending, invoices, events = _stores(decided_meanwhile=True)

    # Act
    with pytest.raises(CloseDecisionError) as raised:
        _decide(pending, invoices, events)

    # Assert
    assert raised.value.problem == DecisionProblem.NOT_DECIDABLE
    assert (invoices.documents["S1"]["isOpen"], events.documents) == (True, {})


def test_decide_close_runs_every_write_inside_one_transaction():
    # Arrange
    pending, invoices, events = _stores()
    calls = []

    def run(callback):
        calls.append("transaction")
        return callback("session")

    # Act
    decision = _decide(pending, invoices, events, run)

    # Assert
    assert (calls, decision.invoice_closed, len(events.documents)) == (["transaction"], True, 1)
