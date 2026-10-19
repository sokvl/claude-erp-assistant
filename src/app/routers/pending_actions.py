from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from pymongo.database import Database

from app.auth.roles import Principal, Role
from app.db import TransactionRunner, get_database, get_transaction_runner
from app.invoices.closing import CloseDecisionError, DecisionProblem, decide_close
from app.invoices.events import INVOICE_EVENTS_COLLECTION
from app.invoices.pending_actions import PENDING_ACTIONS_COLLECTION
from app.limits import MAX_CLOSE_REASON_LENGTH
from app.security import require_role
from app.utils.dates import today_in_business_timezone

router = APIRouter(prefix="/pending-actions", tags=["pending-actions"])

manager = require_role(Role.MANAGER)

PROBLEM_STATUS = {
    DecisionProblem.NOT_DECIDABLE: status.HTTP_409_CONFLICT,
    DecisionProblem.INVALID_PAYMENT_DATE: status.HTTP_422_UNPROCESSABLE_CONTENT,
}


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(None, max_length=MAX_CLOSE_REASON_LENGTH)
    paid_on: date | None = None


def _decide(
    db: Database, run: TransactionRunner, action_id: str, decided_by: str, approve: bool, body: DecisionRequest
) -> dict[str, object]:
    try:
        decision = decide_close(
            db[PENDING_ACTIONS_COLLECTION],
            db["invoices"],
            db[INVOICE_EVENTS_COLLECTION],
            run,
            action_id,
            decided_by,
            approve,
            body.reason,
            body.paid_on,
            today_in_business_timezone(),
        )
    except CloseDecisionError as exc:
        raise HTTPException(status_code=PROBLEM_STATUS[exc.problem], detail=exc.message) from exc
    return {
        "pendingActionId": decision.action_id,
        "status": decision.status,
        "invoiceId": decision.invoice_id,
        "invoiceClosed": decision.invoice_closed,
    }


@router.post("/{action_id}/approve")
def approve_pending_action(
    action_id: str,
    body: DecisionRequest = DecisionRequest(),
    db: Database = Depends(get_database),
    run: TransactionRunner = Depends(get_transaction_runner),
    principal: Principal = Depends(manager),
):
    return _decide(db, run, action_id, principal.username, True, body)


@router.post("/{action_id}/reject")
def reject_pending_action(
    action_id: str,
    body: DecisionRequest = DecisionRequest(),
    db: Database = Depends(get_database),
    run: TransactionRunner = Depends(get_transaction_runner),
    principal: Principal = Depends(manager),
):
    return _decide(db, run, action_id, principal.username, False, body)
