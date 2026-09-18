from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pymongo.database import Database

from app.db import get_database
from app.invoices.schemas import InvoiceAnalyticsParams, InvoiceListParams
from app.invoices.service import analyze_invoices, list_invoices
from app.security import require_api_key

router = APIRouter(prefix="/invoices", tags=["invoices"], dependencies=[Depends(require_api_key)])


@router.get("")
def list_invoice_records(
    params: Annotated[InvoiceListParams, Query()],
    db: Database = Depends(get_database),
):
    return list_invoices(db["invoices"], params)


@router.get("/analytics")
def invoice_analytics(
    params: Annotated[InvoiceAnalyticsParams, Query()],
    db: Database = Depends(get_database),
):
    return analyze_invoices(db["invoices"], params)
