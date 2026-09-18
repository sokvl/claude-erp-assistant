import pytest
from pydantic import ValidationError

from app.catalog.enums import SortField, SortOrder
from app.catalog.schemas import ProductSearchParams
from app.limits import (
    MAX_PAGE,
    MAX_PAGE_SIZE,
    MAX_PRICE,
    MAX_TFLOPS,
    MAX_USE_CASES,
    MAX_VRAM_GB,
)


def test_product_search_params_defaults_are_first_page_sorted_by_name():
    # Arrange / Act
    params = ProductSearchParams()

    # Assert
    assert (params.page, params.page_size, params.sort_by, params.sort_order, params.use_case) == (
        1,
        20,
        SortField.NAME,
        SortOrder.ASC,
        [],
    )


def test_limits_keep_maximum_skip_inside_bson_int64():
    # Arrange / Act
    max_skip = (MAX_PAGE - 1) * MAX_PAGE_SIZE

    # Assert
    assert max_skip <= 2**63 - 1


@pytest.mark.parametrize(
    "kwargs",
    [
        {"page": 1, "page_size": 1},
        {"page": MAX_PAGE, "page_size": MAX_PAGE_SIZE},
        {"min_price": 0},
        {"min_vram_gb": 0},
        {"min_fp16_tflops": 0},
        {"min_vram_gb": MAX_VRAM_GB, "max_vram_gb": MAX_VRAM_GB},
        {"min_price": MAX_PRICE, "max_price": MAX_PRICE},
        {"min_fp16_tflops": MAX_TFLOPS},
        {"min_vram_gb": 24, "max_vram_gb": 80},
        {"sort_by": "vram", "sort_order": "desc"},
        {"category": "GPU", "brand": "Western Digital", "architecture": "Hopper", "memory_type": "GDDR6 ECC"},
        {"use_case": ["training"] * MAX_USE_CASES},
        {"requires_pooling": False},
    ],
    ids=["min_page_and_size", "page_and_size_at_cap", "price_zero", "vram_zero",
         "fp16_zero", "vram_at_cap_equal_bounds", "price_at_cap_equal_bounds",
         "fp16_at_cap", "vram_valid_range", "sort_by_string_coerced",
         "vocabulary_values", "use_cases_at_cap", "pooling_false"],
)
def test_product_search_params_accepts_valid_input(kwargs):
    # Arrange / Act / Assert
    assert ProductSearchParams(**kwargs)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"page": 0},
        {"page": -1},
        {"page": MAX_PAGE + 1},
        {"page": 10**18},
        {"page_size": 0},
        {"page_size": MAX_PAGE_SIZE + 1},
        {"min_vram_gb": -1},
        {"min_vram_gb": MAX_VRAM_GB + 1},
        {"max_vram_gb": MAX_VRAM_GB + 1},
        {"min_vram_gb": 2**63},
        {"min_vram_gb": 10**30},
        {"min_price": -1},
        {"max_price": -1},
        {"min_price": MAX_PRICE + 1},
        {"min_price": float("inf")},
        {"min_price": "1e400"},
        {"min_price": float("nan")},
        {"min_fp16_tflops": -1},
        {"min_fp16_tflops": MAX_TFLOPS + 1},
        {"min_fp16_tflops": float("inf")},
        {"category": "Widget"},
        {"brand": "nvidia"},
        {"use_case": ["training"] * (MAX_USE_CASES + 1)},
        {"use_case": ["mining"]},
        {"sort_by": "listPrice"},
        {"sort_order": "sideways"},
        {"min_vram": 24},
        {"vram_gb": 24},
        {"min_vram_gb": 80, "max_vram_gb": 8},
        {"min_price": 500, "max_price": 100},
    ],
    ids=["page_zero", "page_negative", "page_over_cap", "page_skip_overflow",
         "page_size_zero", "page_size_over_cap", "min_vram_negative",
         "min_vram_over_cap", "max_vram_over_cap", "vram_over_int64", "vram_absurd",
         "min_price_negative", "max_price_negative", "price_over_cap", "price_inf",
         "price_overflows_to_inf", "price_nan", "fp16_negative", "fp16_over_cap",
         "fp16_inf", "unknown_category", "brand_wrong_case", "use_cases_over_cap",
         "unknown_use_case", "sort_by_raw_path", "sort_order_invalid",
         "typo_min_vram", "typo_vram_gb", "vram_inverted", "price_inverted"],
)
def test_product_search_params_rejects_invalid_input(kwargs):
    # Arrange / Act / Assert
    with pytest.raises(ValidationError):
        ProductSearchParams(**kwargs)
