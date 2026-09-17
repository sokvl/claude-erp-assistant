from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pymongo.collection import Collection

from app.catalog import vocab
from app.catalog.schemas import ProductSearchParams
from app.catalog.service import search_catalog
from app.db import products_collection
from app.security import require_api_key

router = APIRouter(prefix="/products", tags=["products"], dependencies=[Depends(require_api_key)])


@router.get("/facets")
def list_facets(collection: Collection = Depends(products_collection)):
    return vocab.get_all_vocabularies(collection)


@router.get("")
def list_products(
    params: Annotated[ProductSearchParams, Query()],
    collection: Collection = Depends(products_collection),
):
    try:
        return search_catalog(collection, params)
    except vocab.UnknownVocabularyValue as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"{exc}. See /products/facets for allowed values.",
        ) from exc
