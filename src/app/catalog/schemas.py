from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.catalog.enums import SortField, SortOrder
from app.limits import (
    MAX_PAGE,
    MAX_PAGE_SIZE,
    MAX_PRICE,
    MAX_TEXT_LENGTH,
    MAX_TFLOPS,
    MAX_USE_CASES,
    MAX_VRAM_GB,
)

VocabValue = Annotated[str, Field(max_length=MAX_TEXT_LENGTH)]


class ProductSearchParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: VocabValue | None = None
    brand: VocabValue | None = None
    architecture: VocabValue | None = None
    memory_type: VocabValue | None = None
    use_case: list[VocabValue] = Field(default_factory=list, max_length=MAX_USE_CASES)

    min_vram_gb: int | None = Field(None, ge=0, le=MAX_VRAM_GB)
    max_vram_gb: int | None = Field(None, ge=0, le=MAX_VRAM_GB)
    min_fp16_tflops: float | None = Field(None, ge=0, le=MAX_TFLOPS, allow_inf_nan=False)
    min_price: float | None = Field(None, ge=0, le=MAX_PRICE, allow_inf_nan=False)
    max_price: float | None = Field(None, ge=0, le=MAX_PRICE, allow_inf_nan=False)
    requires_pooling: bool | None = None

    sort_by: SortField = SortField.NAME
    sort_order: SortOrder = SortOrder.ASC
    page: int = Field(1, ge=1, le=MAX_PAGE)
    page_size: int = Field(20, ge=1, le=MAX_PAGE_SIZE)

    @model_validator(mode="after")
    def _reject_inverted_ranges(self) -> Self:
        for low, high in (("min_vram_gb", "max_vram_gb"), ("min_price", "max_price")):
            lo, hi = getattr(self, low), getattr(self, high)
            if lo is not None and hi is not None and lo > hi:
                raise ValueError(f"{low} ({lo}) must not exceed {high} ({hi})")
        return self
