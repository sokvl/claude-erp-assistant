from collections.abc import Sequence
from typing import Any

from app.catalog.enums import SORT_PATHS, SortField, SortOrder


def _range(minimum: float | None, maximum: float | None) -> dict[str, Any]:
    bounds: dict[str, Any] = {}
    # `is not None`, not truthiness: 0 is a legitimate bound.
    if minimum is not None:
        bounds["$gte"] = minimum
    if maximum is not None:
        bounds["$lte"] = maximum
    return bounds


def build_product_filter(
    *,
    category: str | None = None,
    brand: str | None = None,
    architecture: str | None = None,
    memory_type: str | None = None,
    use_cases: Sequence[str] | None = None,
    min_vram_gb: int | None = None,
    max_vram_gb: int | None = None,
    min_fp16_tflops: float | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    requires_pooling: bool | None = None,
) -> dict[str, Any]:
    """Build `$match` criteria. Contradictory bounds pass through; rejecting them is the request layer's job."""
    criteria: dict[str, Any] = {}

    if category:
        criteria["category"] = category
    if brand:
        criteria["brand"] = brand
    if architecture:
        criteria["specs.architecture"] = architecture
    if memory_type:
        criteria["specs.memoryType"] = memory_type

    if use_cases:
        criteria["specs.useCases"] = {"$in": list(use_cases)}

    vram = _range(min_vram_gb, max_vram_gb)
    if vram:
        criteria["specs.vramGb"] = vram

    fp16 = _range(min_fp16_tflops, None)
    if fp16:
        criteria["specs.fp16TensorTflopsDense"] = fp16

    price = _range(min_price, max_price)
    if price:
        criteria["listPrice"] = price

    if requires_pooling is not None:
        criteria["specs.multiGpuScaling"] = requires_pooling

    return criteria


def build_search_pipeline(
    *,
    criteria: dict[str, Any],
    sort_by: SortField,
    order: SortOrder,
    page: int,
    page_size: int,
) -> list[dict[str, Any]]:
    """Page + filter-aware total in one round trip.

    $match stays first so it can use an index. Inside $facet the sort cannot be
    index-provided; irrelevant at this size, but past ~10^5 docs find+count wins.
    """
    if not isinstance(sort_by, SortField):
        raise ValueError(f"sort_by must be a SortField, got {sort_by!r}")
    if not isinstance(order, SortOrder):
        raise ValueError(f"order must be a SortOrder, got {order!r}")

    path = SORT_PATHS[sort_by]
    direction = 1 if order is SortOrder.ASC else -1

    if path.startswith("specs.") and path not in criteria:
        criteria = {**criteria, path: {"$ne": None}}

    return [
        {"$match": criteria},
        {
            "$facet": {
                "items": [
                    {"$sort": {path: direction, "_id": direction}},
                    {"$skip": (page - 1) * page_size},
                    {"$limit": page_size},
                ],
                "total": [{"$count": "count"}],
            }
        },
        {"$addFields": {"total": {"$ifNull": [{"$arrayElemAt": ["$total.count", 0]}, 0]}}},
    ]
