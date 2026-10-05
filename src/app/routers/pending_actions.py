from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from pymongo.database import Database

from app.db import get_database
from app.invoices.pending_actions import (
    PENDING_ACTIONS_COLLECTION,
    decide_pending_action,
    record_outcome,
)
from app.invoices.service import close_invoice
from app.limits import MAX_CLOSE_REASON_LENGTH
from app.security import require_api_key

router = APIRouter(
    prefix="/pending-actions", tags=["pending-actions"], dependencies=[Depends(require_api_key)]
)


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(None, max_length=MAX_CLOSE_REASON_LENGTH)


def _decide(db: Database, action_id: str, approve: bool, reason: str | None) -> dict[str, Any]:
    collection = db[PENDING_ACTIONS_COLLECTION]
    action = decide_pending_action(collection, action_id, approve, reason)
    if action is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Unknown, expired, or already-decided pending action",
        )
    closed = False
    if approve:
        closed = close_invoice(db["invoices"], action["invoiceId"], action["reason"])
        record_outcome(collection, action_id, closed)
    return {
        "pendingActionId": action_id,
        "status": action["status"],
        "invoiceId": action["invoiceId"],
        "invoiceClosed": closed,
    }


@router.post("/{action_id}/approve")
def approve_pending_action(
    action_id: str,
    body: DecisionRequest = DecisionRequest(),
    db: Database = Depends(get_database),
):
    return _decide(db, action_id, True, body.reason)


@router.post("/{action_id}/reject")
def reject_pending_action(
    action_id: str,
    body: DecisionRequest = DecisionRequest(),
    db: Database = Depends(get_database),
):
    return _decide(db, action_id, False, body.reason)
