from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pymongo.database import Database

from app.catalog import vocab
from app.catalog.schemas import ProductSearchParams
from app.catalog.service import search_catalog
from app.db import get_database
from app.security import require_api_key

router = APIRouter(prefix="/products", tags=["products"], dependencies=[Depends(require_api_key)])


@router.get("/facets")
def list_facets(db: Database = Depends(get_database)):
    return vocab.get_all_vocabularies(db["products"])


@router.get("")
def list_products(
    params: Annotated[ProductSearchParams, Query()],
    db: Database = Depends(get_database),
):
    return search_catalog(db["products"], params)
