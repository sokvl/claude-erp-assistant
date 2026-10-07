from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pymongo.database import Database

from app.auth.roles import Principal, Role
from app.charts.storage import CHART_COLLECTION, get_chart, recent_charts
from app.db import get_database
from app.limits import MAX_CONVERSATION_ID_LENGTH, MAX_RECENT_CHARTS
from app.security import require_role

router = APIRouter(prefix="/charts", tags=["charts"])

manager = require_role(Role.MANAGER)


@router.get("")
def list_recent_charts(
    conversation_id: Annotated[str, Query(max_length=MAX_CONVERSATION_ID_LENGTH)],
    limit: Annotated[int, Query(ge=1, le=MAX_RECENT_CHARTS)] = MAX_RECENT_CHARTS,
    db: Database = Depends(get_database),
    principal: Principal = Depends(manager),
):
    return {"items": recent_charts(db[CHART_COLLECTION], conversation_id, principal.username, limit)}


@router.get("/{chart_id}/image")
def get_chart_image(
    chart_id: str,
    db: Database = Depends(get_database),
    principal: Principal = Depends(manager),
) -> Response:
    chart = get_chart(db[CHART_COLLECTION], chart_id, principal.username)
    if chart is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown chart")
    return Response(
        content=bytes(chart["image"]),
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=86400, immutable"},
    )
