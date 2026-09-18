from datetime import date
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.catalog.enums import SortOrder
from app.invoices.enums import GroupBy, InvoiceSortField, InvoiceStatus
from app.limits import MAX_AMOUNT, MAX_ANALYTICS_ROWS, MAX_PAGE, MAX_PAGE_SIZE, MAX_TEXT_LENGTH


class InvoiceFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    posted_from: date | None = None
    posted_to: date | None = None
    customer: str | None = Field(None, max_length=MAX_TEXT_LENGTH)
    currency: str | None = Field(None, pattern=r"^[A-Z]{3}$")
    status: InvoiceStatus | None = None
    min_amount: float | None = Field(None, ge=0, le=MAX_AMOUNT, allow_inf_nan=False)
    max_amount: float | None = Field(None, ge=0, le=MAX_AMOUNT, allow_inf_nan=False)
    as_of: date | None = None

    @model_validator(mode="after")
    def _reject_inverted_ranges(self) -> Self:
        for low, high in (("posted_from", "posted_to"), ("min_amount", "max_amount")):
            lo, hi = getattr(self, low), getattr(self, high)
            if lo is not None and hi is not None and lo > hi:
                raise ValueError(f"{low} ({lo}) must not exceed {high} ({hi})")
        return self


class InvoiceListParams(InvoiceFilter):
    sort_by: InvoiceSortField = InvoiceSortField.POSTING_DATE
    sort_order: SortOrder = SortOrder.DESC
    page: int = Field(1, ge=1, le=MAX_PAGE)
    page_size: int = Field(20, ge=1, le=MAX_PAGE_SIZE)


class InvoiceAnalyticsParams(InvoiceFilter):
    group_by: GroupBy | None = None
    limit: int | None = Field(None, ge=1, le=MAX_ANALYTICS_ROWS)
