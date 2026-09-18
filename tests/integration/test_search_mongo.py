import pytest

from app.catalog.enums import SortField, SortOrder
from app.catalog.query import build_product_filter, build_search_pipeline
from app.catalog.service import search_products
from app.config import API_KEY
from app.limits import MAX_PAGE, MAX_PAGE_SIZE, MAX_PRICE, MAX_VRAM_GB

pytestmark = pytest.mark.integration

TOTAL_FIXTURE_DOCS = 7
GPU_COUNT = 5


def _search(products, criteria, **overrides):
    kwargs = {
        "criteria": criteria,
        "sort_by": SortField.NAME,
        "order": SortOrder.ASC,
        "page": 1,
        "page_size": 20,
    }
    kwargs.update(overrides)
    return search_products(products, **kwargs)


@pytest.mark.parametrize(
    ("filter_kwargs", "expected_skus"),
    [
        ({}, ["CPU-TEST", "GPU-AMD-NULL", "GPU-BIG", "GPU-HUGE", "GPU-MID",
              "GPU-SMALL", "RAM-TEST"]),
        ({"min_vram_gb": 24}, ["GPU-AMD-NULL", "GPU-BIG", "GPU-HUGE", "GPU-MID"]),
        ({"min_vram_gb": 80}, ["GPU-BIG", "GPU-HUGE"]),
        ({"max_vram_gb": 24}, ["GPU-AMD-NULL", "GPU-MID", "GPU-SMALL"]),
        ({"min_vram_gb": 24, "max_vram_gb": 80}, ["GPU-AMD-NULL", "GPU-BIG", "GPU-MID"]),
        ({"min_vram_gb": 999999}, []),
        ({"category": "GPU"}, ["GPU-AMD-NULL", "GPU-BIG", "GPU-HUGE", "GPU-MID", "GPU-SMALL"]),
        ({"brand": "AMD"}, ["CPU-TEST", "GPU-AMD-NULL", "GPU-HUGE"]),
        ({"architecture": "Hopper"}, ["GPU-BIG"]),
        ({"memory_type": "HBM3"}, ["GPU-BIG", "GPU-HUGE"]),
        ({"use_cases": ["training"]}, ["GPU-BIG", "GPU-HUGE"]),
        ({"use_cases": ["gaming", "training"]},
         ["GPU-AMD-NULL", "GPU-BIG", "GPU-HUGE", "GPU-MID", "GPU-SMALL"]),
        ({"requires_pooling": True}, ["GPU-BIG", "GPU-HUGE"]),
        ({"requires_pooling": False}, ["GPU-AMD-NULL", "GPU-MID", "GPU-SMALL"]),
        # the "train a neural net" scenario
        ({"min_vram_gb": 80, "min_fp16_tflops": 900.0, "requires_pooling": True},
         ["GPU-BIG", "GPU-HUGE"]),
        # contradictory bounds are well-formed and simply match nothing
        ({"min_vram_gb": 80, "max_vram_gb": 8}, []),
    ],
    ids=["no_filters", "min_vram_24", "min_vram_80", "max_vram_24", "vram_range",
         "vram_unreachable", "category", "brand", "architecture", "memory_type",
         "use_case_single", "use_case_any_of", "pooling_true", "pooling_false",
         "training_scenario", "inverted_range"],
)
def test_search_products_returns_expected_documents(products, filter_kwargs, expected_skus):
    # Arrange
    criteria = build_product_filter(**filter_kwargs)

    # Act
    result = _search(products, criteria)

    # Assert
    assert sorted(item["_id"] for item in result["items"]) == sorted(expected_skus)


@pytest.mark.parametrize(
    ("filter_kwargs", "expected_total"),
    [
        ({}, TOTAL_FIXTURE_DOCS),
        ({"category": "GPU"}, GPU_COUNT),
        ({"min_vram_gb": 80}, 2),
        ({"min_vram_gb": 999999}, 0),
    ],
    ids=["unfiltered", "category", "min_vram", "no_matches"],
)
def test_search_products_total_reflects_the_filter(products, filter_kwargs, expected_total):
    # Arrange
    criteria = build_product_filter(**filter_kwargs)

    # Act
    result = _search(products, criteria)

    # Assert: an estimated count would report the whole collection instead
    assert result["total"] == expected_total


@pytest.mark.parametrize(
    "spec_sort",
    [SortField.VRAM, SortField.FP16],
    ids=["vram", "fp16"],
)
def test_search_products_spec_sort_excludes_products_without_specs(products, spec_sort):
    # Arrange / Act: nulls sort lowest, so unguarded this leads with CPU/RAM
    result = _search(products, {}, sort_by=spec_sort, order=SortOrder.ASC)

    # Assert
    assert [item["_id"] for item in result["items"]] == [
        "GPU-SMALL", "GPU-AMD-NULL", "GPU-MID", "GPU-BIG", "GPU-HUGE",
    ]


def test_search_products_spec_sort_with_filter_keeps_the_filter(products):
    # Arrange
    criteria = build_product_filter(min_vram_gb=80)

    # Act
    result = _search(products, criteria, sort_by=SortField.VRAM, order=SortOrder.DESC)

    # Assert: the null guard must not overwrite the caller's bound
    assert [item["_id"] for item in result["items"]] == ["GPU-HUGE", "GPU-BIG"]


def test_search_products_pagination_is_stable_across_tied_sort_keys(products):
    # Arrange: GPU-MID and CPU-TEST share listPrice 1499.0
    criteria = build_product_filter()

    # Act
    pages = [
        _search(products, criteria, sort_by=SortField.PRICE, page=page, page_size=2)
        for page in (1, 2, 3, 4)
    ]

    # Assert
    seen = [item["_id"] for page in pages for item in page["items"]]
    assert len(seen) == len(set(seen)) == TOTAL_FIXTURE_DOCS


def test_search_products_match_stage_uses_an_index(products):
    # Arrange
    criteria = build_product_filter(category="GPU")
    pipeline = build_search_pipeline(
        criteria=criteria, sort_by=SortField.NAME, order=SortOrder.ASC,
        page=1, page_size=20,
    )

    # Act
    plan = products.database.command(
        "explain",
        {"aggregate": products.name, "pipeline": pipeline, "cursor": {}},
        verbosity="queryPlanner",
    )

    # Assert: $match stays first, so it is planned as an ordinary query
    assert "IXSCAN" in str(plan)


@pytest.mark.parametrize(
    "query",
    [
        f"?min_vram_gb={MAX_VRAM_GB}",
        f"?page={MAX_PAGE}&page_size={MAX_PAGE_SIZE}",
        f"?max_price={MAX_PRICE:.0f}&sort_by=vram",
    ],
    ids=["vram_at_cap", "max_skip", "price_at_cap_with_spec_sort"],
)
def test_list_products_values_at_cap_encode_and_execute_against_mongo(client, query):
    # Arrange / Act
    response = client.get(f"/products{query}", headers={"X-API-Key": API_KEY})

    # Assert
    assert response.status_code == 200
