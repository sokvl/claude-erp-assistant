from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from bson import Binary

from app.charts.schemas import ChartParams
from app.limits import CHART_TTL_DAYS, MAX_CHART_BYTES, MAX_RECENT_CHARTS, QUERY_TIMEOUT_MS

CHART_COLLECTION = "charts"

METADATA_PROJECTION = {"image": 0}


def save_chart(
    collection: Any,
    conversation_id: str | None,
    params: ChartParams,
    title: str,
    image: bytes,
) -> str:
    if len(image) > MAX_CHART_BYTES:
        raise ValueError(f"chart is {len(image)} bytes, over the {MAX_CHART_BYTES} byte limit")
    created_at = datetime.now(UTC)
    document = {
        "_id": uuid4().hex,
        "conversationId": conversation_id,
        "createdAt": created_at,
        "expiresAt": created_at + timedelta(days=CHART_TTL_DAYS),
        "title": title,
        "chartType": params.chart_type,
        "metric": params.metric,
        "groupBy": params.group_by,
        "image": Binary(image),
    }
    collection.insert_one(document)
    return document["_id"]


def get_chart(collection: Any, chart_id: str) -> dict[str, Any] | None:
    return collection.find_one({"_id": chart_id}, max_time_ms=QUERY_TIMEOUT_MS)


def recent_charts(collection: Any, conversation_id: str, limit: int = MAX_RECENT_CHARTS) -> list[dict[str, Any]]:
    return list(
        collection.find(
            {"conversationId": conversation_id},
            METADATA_PROJECTION,
            sort=[("createdAt", -1)],
            limit=limit,
            max_time_ms=QUERY_TIMEOUT_MS,
        )
    )
