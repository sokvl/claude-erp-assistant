from typing import Any

from app.catalog import vocab
from app.catalog.enums import SortField, SortOrder
from app.catalog.query import build_product_filter, build_search_pipeline
from app.catalog.schemas import ProductSearchParams
from app.limits import QUERY_TIMEOUT_MS


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
    cursor = collection.aggregate(pipeline, maxTimeMS=QUERY_TIMEOUT_MS)
    result = next(iter(cursor), None) or {"items": [], "total": 0}
    return {
        "page": page,
        "pageSize": page_size,
        "total": result["total"],
        "items": result["items"],
    }


def search_catalog(collection: Any, params: ProductSearchParams) -> dict[str, Any]:
    for param in vocab.VOCAB_FIELDS:
        value = getattr(params, param)
        if value:
            vocab.check_vocabulary(collection, param, value if isinstance(value, list) else [value])

    criteria = build_product_filter(
        category=params.category,
        brand=params.brand,
        architecture=params.architecture,
        memory_type=params.memory_type,
        use_cases=params.use_case,
        min_vram_gb=params.min_vram_gb,
        max_vram_gb=params.max_vram_gb,
        min_fp16_tflops=params.min_fp16_tflops,
        min_price=params.min_price,
        max_price=params.max_price,
        requires_pooling=params.requires_pooling,
    )
    return search_products(
        collection,
        criteria=criteria,
        sort_by=params.sort_by,
        order=params.sort_order,
        page=params.page,
        page_size=params.page_size,
    )
