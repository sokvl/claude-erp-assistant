from fastapi import APIRouter, Depends, Query
from pymongo.database import Database

from app.db import get_database
from app.limits import MAX_PAGE, MAX_PAGE_SIZE
from app.pagination import paginate
from app.security import require_api_key

router = APIRouter(prefix="/invoices", tags=["invoices"], dependencies=[Depends(require_api_key)])


@router.get("")
def list_invoices(
    page: int = Query(1, ge=1, le=MAX_PAGE),
    page_size: int = Query(20, ge=1, le=MAX_PAGE_SIZE),
    db: Database = Depends(get_database),
):
    return paginate(db["invoices"], page, page_size)
