from datetime import datetime

import pytest

from app.utils.mongo import range_filter


@pytest.mark.parametrize(
    ("minimum", "maximum", "expected"),
    [
        (None, None, {}),
        (10, None, {"$gte": 10}),
        (None, 10, {"$lte": 10}),
        (10, 20, {"$gte": 10, "$lte": 20}),
        (0, 0, {"$gte": 0, "$lte": 0}),
        (0.5, 1.5, {"$gte": 0.5, "$lte": 1.5}),
        (datetime(2026, 1, 1), datetime(2026, 1, 31), {"$gte": datetime(2026, 1, 1), "$lte": datetime(2026, 1, 31)}),
    ],
    ids=["no_bounds", "min_only", "max_only", "both", "zero_is_a_bound", "floats", "datetimes"],
)
def test_range_filter_bounds_maps_to_gte_lte(minimum, maximum, expected):
    # Arrange / Act
    bounds = range_filter(minimum, maximum)

    # Assert: `is not None`, not truthiness, so 0 still bounds the range
    assert bounds == expected
