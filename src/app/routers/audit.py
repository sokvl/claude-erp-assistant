from typing import Any

from fastapi import APIRouter, Depends, Path
from pymongo.database import Database

from app.auth.roles import Role
from app.db import get_database
from app.invoices.events import INVOICE_EVENTS_COLLECTION, list_events
from app.limits import MAX_TEXT_LENGTH
from app.security import require_role

router = APIRouter(prefix="/audit", tags=["audit"], dependencies=[Depends(require_role(Role.ADMIN))])


@router.get("/invoices/{invoice_id}/events")
def invoice_events(
    invoice_id: str = Path(max_length=MAX_TEXT_LENGTH),
    db: Database = Depends(get_database),
) -> dict[str, Any]:
    events = list_events(db[INVOICE_EVENTS_COLLECTION], invoice_id)
    return {"invoiceId": invoice_id, "events": [present_event(event) for event in events]}


def present_event(event: dict[str, Any]) -> dict[str, Any]:
    return {"id": event["_id"], **{key: value for key, value in event.items() if key != "_id"}}
