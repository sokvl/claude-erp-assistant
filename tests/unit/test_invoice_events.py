from datetime import UTC, date, datetime

import pytest

from app.invoices.events import (
    HISTORY_SORT,
    Actor,
    ActorType,
    EventType,
    build_event,
    list_events,
    record_event,
)
from app.limits import MAX_INVOICE_EVENTS, QUERY_TIMEOUT_MS

AT = datetime(2026, 10, 19, 6, 51, tzinfo=UTC)
ANNA = Actor(ActorType.USER, "anna")


class Events:
    def __init__(self, stored=()):
        self.stored = list(stored)
        self.inserts = []
        self.finds = []

    def insert_one(self, document, session=None):
        self.inserts.append((document, session))

    def find(self, criteria, **options):
        self.finds.append((criteria, options))
        return iter(self.stored)


def test_build_event_manual_close_records_who_when_and_the_payment_date():
    # Arrange / Act
    event = build_event(
        "S000000008", EventType.CLOSED, ANNA, AT,
        reason="paid by wire", paid_on=date(2026, 10, 3), suggested_paid_on=date(2026, 10, 2),
        action_id="8b5e", conversation_id="ccf2",
    )

    # Assert
    assert {key: value for key, value in event.items() if key != "_id"} == {
        "invoiceId": "S000000008",
        "type": "closed",
        "at": AT,
        "actor": {"type": "user", "id": "anna"},
        "reason": "paid by wire",
        "paidOn": datetime(2026, 10, 3, tzinfo=UTC),
        "suggestedPaidOn": datetime(2026, 10, 2, tzinfo=UTC),
        "actionId": "8b5e",
        "conversationId": "ccf2",
    }


# A bank statement import closes invoices without any request or conversation behind it.
def test_build_event_system_close_has_no_request_or_conversation():
    # Arrange / Act
    event = build_event("S1", EventType.CLOSED, Actor(ActorType.SYSTEM, "bank_statement"), AT, paid_on=date(2026, 10, 3))

    # Assert
    assert (event["actor"], event["actionId"], event["conversationId"], event["suggestedPaidOn"]) == (
        {"type": "system", "id": "bank_statement"}, None, None, None
    )


def test_build_event_gives_every_event_its_own_id():
    # Arrange / Act
    ids = {build_event("S1", EventType.CLOSE_REQUESTED, ANNA, AT)["_id"] for _ in range(3)}

    # Assert
    assert len(ids) == 3


@pytest.mark.parametrize("session", [None, object()], ids=["outside_a_transaction", "inside_a_transaction"])
def test_record_event_writes_in_the_given_session_and_returns_the_id(session):
    # Arrange
    events = Events()
    event = build_event("S1", EventType.CLOSE_REJECTED, ANNA, AT, reason="wrong customer")

    # Act
    event_id = record_event(events, event, session)

    # Assert
    assert (event_id, events.inserts) == (event["_id"], [(event, session)])


def test_list_events_reads_one_invoice_in_order_with_a_cap_and_a_timeout():
    # Arrange
    stored = [build_event("S1", EventType.CLOSE_REQUESTED, ANNA, AT), build_event("S1", EventType.CLOSED, ANNA, AT)]
    events = Events(stored)

    # Act
    history = list_events(events, "S1")

    # Assert
    assert history == stored
    assert events.finds == [
        ({"invoiceId": "S1"}, {"sort": HISTORY_SORT, "limit": MAX_INVOICE_EVENTS, "max_time_ms": QUERY_TIMEOUT_MS})
    ]
