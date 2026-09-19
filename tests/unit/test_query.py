import pytest

from app.catalog.enums import SortField, SortOrder
from app.catalog.query import build_product_filter, build_search_pipeline


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        # no filters at all
        ({}, {}),
        # one key per filter
        ({"category": "GPU"}, {"category": "GPU"}),
        ({"brand": "NVIDIA"}, {"brand": "NVIDIA"}),
        ({"architecture": "Hopper"}, {"specs.architecture": "Hopper"}),
        ({"memory_type": "HBM3"}, {"specs.memoryType": "HBM3"}),
        ({"use_cases": ["training"]}, {"specs.useCases": {"$in": ["training"]}}),
        (
            {"use_cases": ["training", "inference"]},
            {"specs.useCases": {"$in": ["training", "inference"]}},
        ),
        ({"min_vram_gb": 24}, {"specs.vramGb": {"$gte": 24}}),
        ({"max_vram_gb": 80}, {"specs.vramGb": {"$lte": 80}}),
        ({"min_fp16_tflops": 900.0}, {"specs.fp16TensorTflopsDense": {"$gte": 900.0}}),
        ({"min_price": 100.0}, {"listPrice": {"$gte": 100.0}}),
        ({"max_price": 500.0}, {"listPrice": {"$lte": 500.0}}),
        ({"requires_pooling": True}, {"specs.multiGpuScaling": True}),
        ({"requires_pooling": False}, {"specs.multiGpuScaling": False}),
        # min+max merge into a single sub-document
        (
            {"min_vram_gb": 24, "max_vram_gb": 80},
            {"specs.vramGb": {"$gte": 24, "$lte": 80}},
        ),
        (
            {"min_price": 100.0, "max_price": 500.0},
            {"listPrice": {"$gte": 100.0, "$lte": 500.0}},
        ),
        # zero is a real bound - a truthiness check would drop these
        ({"min_price": 0.0}, {"listPrice": {"$gte": 0.0}}),
        ({"min_vram_gb": 0}, {"specs.vramGb": {"$gte": 0}}),
        # contradictory / out-of-range values pass through unvalidated
        (
            {"min_vram_gb": 80, "max_vram_gb": 8},
            {"specs.vramGb": {"$gte": 80, "$lte": 8}},
        ),
        ({"min_price": -1.0}, {"listPrice": {"$gte": -1.0}}),
        ({"min_vram_gb": 999999}, {"specs.vramGb": {"$gte": 999999}}),
        # empty values must omit the key: {"brand": None} would match
        # documents where the field is absent, i.e. all 41 non-GPU products
        ({"use_cases": []}, {}),
        ({"use_cases": None}, {}),
        ({"brand": ""}, {}),
        ({"category": ""}, {}),
        # unrelated filters sit side by side, no $and wrapper
        (
            {"category": "GPU", "brand": "NVIDIA", "min_vram_gb": 24},
            {"category": "GPU", "brand": "NVIDIA", "specs.vramGb": {"$gte": 24}},
        ),
        # the "train a neural net" scenario
        (
            {"min_vram_gb": 80, "min_fp16_tflops": 900.0, "requires_pooling": True},
            {
                "specs.vramGb": {"$gte": 80},
                "specs.fp16TensorTflopsDense": {"$gte": 900.0},
                "specs.multiGpuScaling": True,
            },
        ),
        # everything at once - catches key collisions between filters
        (
            {
                "category": "GPU",
                "brand": "NVIDIA",
                "architecture": "Hopper",
                "memory_type": "HBM3",
                "use_cases": ["training"],
                "min_vram_gb": 40,
                "max_vram_gb": 200,
                "min_fp16_tflops": 300.0,
                "min_price": 1000.0,
                "max_price": 50000.0,
                "requires_pooling": True,
            },
            {
                "category": "GPU",
                "brand": "NVIDIA",
                "specs.architecture": "Hopper",
                "specs.memoryType": "HBM3",
                "specs.useCases": {"$in": ["training"]},
                "specs.vramGb": {"$gte": 40, "$lte": 200},
                "specs.fp16TensorTflopsDense": {"$gte": 300.0},
                "listPrice": {"$gte": 1000.0, "$lte": 50000.0},
                "specs.multiGpuScaling": True,
            },
        ),
    ],
    ids=[
        "no_filters", "category", "brand", "architecture", "memory_type",
        "use_case_single", "use_case_multiple", "min_vram", "max_vram",
        "min_fp16", "min_price", "max_price", "pooling_true", "pooling_false",
        "vram_range_merged", "price_range_merged", "min_price_zero",
        "min_vram_zero", "vram_range_inverted", "min_price_negative",
        "min_vram_unreachable", "use_cases_empty_list", "use_cases_none",
        "brand_empty", "category_empty", "three_siblings",
        "training_scenario", "all_filters",
    ],
)
def test_build_product_filter_builds_expected_criteria(kwargs, expected):
    # Arrange / Act
    result = build_product_filter(**kwargs)

    # Assert
    assert result == expected


def test_build_product_filter_positional_argument_raises_type_error():
    # Arrange / Act / Assert
    with pytest.raises(TypeError):
        build_product_filter("GPU")


def _pipeline(**overrides):
    kwargs = {
        "criteria": {},
        "sort_by": SortField.NAME,
        "order": SortOrder.ASC,
        "page": 1,
        "page_size": 20,
    }
    kwargs.update(overrides)
    return build_search_pipeline(**kwargs)


def test_build_search_pipeline_stage_order_is_match_facet_addfields():
    # Arrange / Act
    pipeline = _pipeline()

    # Assert
    assert [next(iter(stage)) for stage in pipeline] == ["$match", "$facet", "$addFields"]


def test_build_search_pipeline_items_branch_order_is_sort_skip_limit():
    # Arrange / Act
    items = _pipeline()[1]["$facet"]["items"]

    # Assert
    assert [next(iter(stage)) for stage in items] == ["$sort", "$skip", "$limit"]


@pytest.mark.parametrize(
    ("page", "page_size", "expected_skip"),
    [(1, 20, 0), (3, 20, 40), (1, 1, 0), (2, 1, 1), (5, 100, 400)],
    ids=["first_page", "third_page", "single_first", "single_second", "large_page"],
)
def test_build_search_pipeline_skip_follows_page_arithmetic(page, page_size, expected_skip):
    # Arrange / Act
    items = _pipeline(page=page, page_size=page_size)[1]["$facet"]["items"]

    # Assert
    assert items[1:] == [{"$skip": expected_skip}, {"$limit": page_size}]


@pytest.mark.parametrize(
    ("sort_by", "order", "expected"),
    [
        (SortField.NAME, SortOrder.ASC, {"name": 1, "_id": 1}),
        (SortField.NAME, SortOrder.DESC, {"name": -1, "_id": -1}),
        (SortField.PRICE, SortOrder.ASC, {"listPrice": 1, "_id": 1}),
        (SortField.VRAM, SortOrder.DESC, {"specs.vramGb": -1, "_id": -1}),
        (SortField.FP16, SortOrder.ASC, {"specs.fp16TensorTflopsDense": 1, "_id": 1}),
        (SortField.RELEASE_YEAR, SortOrder.ASC, {"specs.releaseYear": 1, "_id": 1}),
    ],
    ids=["name_asc", "name_desc", "price_asc", "vram_desc", "fp16_asc", "year_asc"],
)
def test_build_search_pipeline_sort_maps_field_and_appends_id_tiebreaker(
    sort_by, order, expected
):
    # Arrange / Act
    items = _pipeline(sort_by=sort_by, order=order)[1]["$facet"]["items"]

    # Assert
    assert items[0] == {"$sort": expected}


@pytest.mark.parametrize(
    ("criteria", "sort_by", "expected"),
    [
        # nulls sort lowest, so a spec sort without a guard leads with CPUs; the guard names the type it keeps
        # instead of negating null, since a negation cannot bound an index scan
        ({}, SortField.VRAM, {"specs.vramGb": {"$type": "number"}}),
        ({}, SortField.FP16, {"specs.fp16TensorTflopsDense": {"$type": "number"}}),
        # non-spec paths need no guard
        ({}, SortField.NAME, {}),
        ({}, SortField.PRICE, {}),
        # an existing bound already excludes nulls; clobbering it would
        # silently drop the caller's filter
        (
            {"specs.vramGb": {"$gte": 24}},
            SortField.VRAM,
            {"specs.vramGb": {"$gte": 24}},
        ),
        # unrelated criteria survive alongside the guard
        (
            {"category": "GPU"},
            SortField.VRAM,
            {"category": "GPU", "specs.vramGb": {"$type": "number"}},
        ),
    ],
    ids=["vram_guarded", "fp16_guarded", "name_unguarded", "price_unguarded",
         "existing_bound_kept", "guard_plus_criteria"],
)
def test_build_search_pipeline_match_stage_applies_null_guard(criteria, sort_by, expected):
    # Arrange / Act
    pipeline = _pipeline(criteria=criteria, sort_by=sort_by)

    # Assert
    assert pipeline[0] == {"$match": expected}


def test_build_search_pipeline_total_branch_counts_matched_documents():
    # Arrange / Act
    pipeline = _pipeline()

    # Assert
    assert pipeline[1]["$facet"]["total"] == [{"$count": "count"}]


def test_build_search_pipeline_normalizes_empty_total_to_zero():
    # Arrange / Act
    pipeline = _pipeline()

    # Assert: the total facet yields [] on zero matches, which must become 0
    assert pipeline[2] == {
        "$addFields": {"total": {"$ifNull": [{"$arrayElemAt": ["$total.count", 0]}, 0]}}
    }


def test_build_search_pipeline_does_not_mutate_caller_criteria():
    # Arrange
    criteria = {}

    # Act
    _pipeline(criteria=criteria, sort_by=SortField.VRAM)

    # Assert
    assert criteria == {}


@pytest.mark.parametrize(
    ("sort_by", "order"),
    [("listPrice", SortOrder.ASC), ("specs.vramGb", SortOrder.ASC), (SortField.NAME, "asc")],
    ids=["raw_sort_path", "raw_spec_path", "raw_order"],
)
def test_build_search_pipeline_raw_string_raises_value_error(sort_by, order):
    # Arrange / Act / Assert: a raw string must never become a $sort key
    with pytest.raises(ValueError):
        _pipeline(sort_by=sort_by, order=order)
