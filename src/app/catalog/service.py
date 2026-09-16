from typing import Any

from app.catalog.enums import SortField, SortOrder
from app.catalog.query import build_search_pipeline


def search_products(
    collection: Any,
    *,
    criteria: dict[str, Any],
    sort_by: SortField,
    order: SortOrder,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    pipeline = build_search_pipeline(
        criteria=criteria, sort_by=sort_by, order=order, page=page, page_size=page_size
    )
    result = next(iter(collection.aggregate(pipeline)), None) or {"items": [], "total": 0}
    return {
        "page": page,
        "pageSize": page_size,
        "total": result["total"],
        "items": result["items"],
    }
