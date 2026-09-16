from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pymongo.collection import Collection

from app.catalog import vocab
from app.catalog.query import build_product_filter
from app.catalog.schemas import ProductSearchParams
from app.catalog.service import search_products
from app.db import products_collection
from app.security import require_api_key

router = APIRouter(prefix="/products", tags=["products"], dependencies=[Depends(require_api_key)])


def _check_vocabulary(collection: Collection, param: str, values: list[str]) -> None:
    allowed = vocab.get_vocabulary(collection, param)
    for value in values:
        if value not in allowed:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Unknown {param}: {value!r}. See /products/facets for allowed values.",
            )


@router.get("/facets")
def list_facets(collection: Collection = Depends(products_collection)):
    return vocab.get_all_vocabularies(collection)


@router.get("")
def list_products(
    params: Annotated[ProductSearchParams, Query()],
    collection: Collection = Depends(products_collection),
):
    for param in ("category", "brand", "architecture", "memory_type"):
        value = getattr(params, param)
        if value:
            _check_vocabulary(collection, param, [value])
    if params.use_case:
        _check_vocabulary(collection, "use_case", params.use_case)

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
