from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any

from app.db import TransactionRunner
from app.invoices.events import Actor, ActorType, EventType, build_event, record_event
from app.invoices.pending_actions import decide_pending_action, find_decidable_action, record_outcome
from app.invoices.service import check_paid_on, close_invoice, read_posting_date


class DecisionProblem(StrEnum):
    NOT_DECIDABLE = "not_decidable"
    INVALID_PAYMENT_DATE = "invalid_payment_date"


class CloseDecisionError(Exception):
    def __init__(self, problem: DecisionProblem, message: str) -> None:
        super().__init__(message)
        self.problem = problem
        self.message = message


@dataclass(frozen=True)
class CloseDecision:
    action_id: str
    status: str
    invoice_id: str
    invoice_closed: bool


NOT_DECIDABLE_MESSAGE = "Unknown, expired, or already-decided pending action"


def decide_close(
    pending_actions: Any,
    invoices: Any,
    events: Any,
    run_in_transaction: TransactionRunner,
    action_id: str,
    decided_by: str,
    approve: bool,
    decided_reason: str | None,
    paid_on: date | None,
    today: date,
) -> CloseDecision:
    action = find_decidable_action(pending_actions, action_id, decided_by)
    if action is None:
        raise CloseDecisionError(DecisionProblem.NOT_DECIDABLE, NOT_DECIDABLE_MESSAGE)
    if approve:
        problem = check_paid_on(paid_on, read_posting_date(invoices, action["invoiceId"]), today)
        if problem:
            raise CloseDecisionError(DecisionProblem.INVALID_PAYMENT_DATE, problem)

    def write(session: Any) -> CloseDecision:
        decided = decide_pending_action(
            pending_actions, action_id, decided_by, approve, decided_reason, paid_on if approve else None, session
        )
        if decided is None:
            raise CloseDecisionError(DecisionProblem.NOT_DECIDABLE, NOT_DECIDABLE_MESSAGE)
        closed = False
        if approve:
            closed = close_invoice(invoices, decided["invoiceId"], paid_on, session)
            record_outcome(pending_actions, action_id, closed, session)
        if closed or not approve:
            record_event(events, build_decision_event(decided, decided_by, closed, paid_on), session)
        return CloseDecision(action_id, decided["status"], decided["invoiceId"], closed)

    return run_in_transaction(write)


def build_decision_event(action: dict[str, Any], decided_by: str, closed: bool, paid_on: date | None) -> dict[str, Any]:
    suggested = action.get("suggestedPaidOn")
    return build_event(
        action["invoiceId"],
        EventType.CLOSED if closed else EventType.CLOSE_REJECTED,
        Actor(ActorType.USER, decided_by),
        datetime.now(UTC),
        reason=action["reason"] if closed else action.get("decidedReason"),
        paid_on=paid_on if closed else None,
        suggested_paid_on=suggested.date() if suggested else None,
        action_id=action["_id"],
        conversation_id=action.get("conversationId"),
    )
