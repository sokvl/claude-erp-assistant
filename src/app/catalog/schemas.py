from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.catalog.enums import SortField, SortOrder

MAX_PAGE_SIZE = 100


class ProductSearchParams(BaseModel):
    # extra="forbid" turns a typo like ?min_vram=24 into a 422 rather than a
    # silently ignored filter.
    model_config = ConfigDict(extra="forbid")

    # Vocabulary params are plain str here and checked against the live DB
    # vocabulary in the router - the allowed values aren't known at import time.
    category: str | None = None
    brand: str | None = None
    architecture: str | None = None
    memory_type: str | None = None
    use_case: list[str] = Field(default_factory=list)

    min_vram_gb: int | None = Field(None, ge=0)
    max_vram_gb: int | None = Field(None, ge=0)
    min_fp16_tflops: float | None = Field(None, ge=0)
    min_price: float | None = Field(None, ge=0)
    max_price: float | None = Field(None, ge=0)
    requires_pooling: bool | None = None

    sort_by: SortField = SortField.NAME
    sort_order: SortOrder = SortOrder.ASC
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=MAX_PAGE_SIZE)

    @model_validator(mode="after")
    def _reject_inverted_ranges(self) -> Self:
        for low, high in (("min_vram_gb", "max_vram_gb"), ("min_price", "max_price")):
            lo, hi = getattr(self, low), getattr(self, high)
            if lo is not None and hi is not None and lo > hi:
                raise ValueError(f"{low} ({lo}) must not exceed {high} ({hi})")
        return self
