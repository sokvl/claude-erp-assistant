from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pymongo.database import Database

from app.analytics.service import analyze_gold, get_gold_settings
from app.auth.roles import Role
from app.db import get_database
from app.invoices.schemas import InvoiceAnalyticsParams, InvoiceListParams
from app.invoices.service import list_invoices
from app.security import require_role
from lake_config.settings import LakeSettings

router = APIRouter(prefix="/invoices", tags=["invoices"], dependencies=[Depends(require_role(Role.MANAGER))])


@router.get("")
def list_invoice_records(
    params: Annotated[InvoiceListParams, Query()],
    db: Database = Depends(get_database),
):
    return list_invoices(db["invoices"], params)


@router.get("/analytics")
def invoice_analytics(
    params: Annotated[InvoiceAnalyticsParams, Query()],
    gold: LakeSettings | None = Depends(get_gold_settings),
):
    return analyze_gold(gold, params)
