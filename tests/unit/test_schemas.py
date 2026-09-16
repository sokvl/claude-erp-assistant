import pytest
from pydantic import ValidationError

from app.catalog.enums import SortField, SortOrder
from app.catalog.schemas import ProductSearchParams


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


@pytest.mark.parametrize(
    "kwargs",
    [
        {"page": 1, "page_size": 1},
        {"page_size": 100},
        {"min_price": 0},
        {"min_vram_gb": 0},
        {"min_fp16_tflops": 0},
        # equal bounds are a valid degenerate range, not an inversion
        {"min_vram_gb": 24, "max_vram_gb": 24},
        {"min_price": 500, "max_price": 500},
        {"min_vram_gb": 24, "max_vram_gb": 80},
        {"sort_by": "vram", "sort_order": "desc"},
        {"use_case": ["training", "inference"]},
        {"requires_pooling": False},
    ],
    ids=["min_page_size", "max_page_size", "price_zero", "vram_zero", "fp16_zero",
         "vram_equal_bounds", "price_equal_bounds", "vram_valid_range",
         "sort_by_string_coerced", "multiple_use_cases", "pooling_false"],
)
def test_product_search_params_accepts_valid_input(kwargs):
    # Arrange / Act / Assert
    assert ProductSearchParams(**kwargs)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"page": 0},
        {"page": -1},
        {"page_size": 0},
        {"page_size": 101},
        {"min_price": -1},
        {"max_price": -1},
        {"min_vram_gb": -1},
        {"min_fp16_tflops": -1},
        {"sort_by": "listPrice"},
        {"sort_order": "sideways"},
        # a typo must fail loudly rather than be silently ignored
        {"min_vram": 24},
        {"vram_gb": 24},
        # inverted ranges are rejected here, not in the query builder
        {"min_vram_gb": 80, "max_vram_gb": 8},
        {"min_price": 500, "max_price": 100},
    ],
    ids=["page_zero", "page_negative", "page_size_zero", "page_size_over_max",
         "min_price_negative", "max_price_negative", "min_vram_negative",
         "min_fp16_negative", "sort_by_raw_path", "sort_order_invalid",
         "typo_min_vram", "typo_vram_gb", "vram_inverted", "price_inverted"],
)
def test_product_search_params_rejects_invalid_input(kwargs):
    # Arrange / Act / Assert
    with pytest.raises(ValidationError):
        ProductSearchParams(**kwargs)
