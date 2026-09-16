import pytest

from app.catalog.enums import SortField, SortOrder
from app.catalog.service import search_products
from app.limits import QUERY_TIMEOUT_MS


class FakeCollection:
    def __init__(self, result):
        self.result = result
        self.pipelines = []
        self.options = []

    def aggregate(self, pipeline, **kwargs):
        self.pipelines.append(pipeline)
        self.options.append(kwargs)
        return iter(self.result)


def _search(collection, **overrides):
    kwargs = {
        "criteria": {},
        "sort_by": SortField.NAME,
        "order": SortOrder.ASC,
        "page": 1,
        "page_size": 20,
    }
    kwargs.update(overrides)
    return search_products(collection, **kwargs)


@pytest.mark.parametrize(
    ("cursor_result", "expected_total", "expected_items"),
    [
        ([{"items": [{"_id": "GPU-H100-80G"}], "total": 1}], 1, [{"_id": "GPU-H100-80G"}]),
        ([{"items": [], "total": 0}], 0, []),
        # $facet always yields one document, but defaulting keeps the
        # function total rather than raising on an empty cursor
        ([], 0, []),
    ],
    ids=["one_match", "no_matches", "empty_cursor"],
)
def test_search_products_unwraps_facet_result(cursor_result, expected_total, expected_items):
    # Arrange
    collection = FakeCollection(cursor_result)

    # Act
    result = _search(collection)

    # Assert
    assert (result["total"], result["items"]) == (expected_total, expected_items)


def test_search_products_echoes_pagination_in_response():
    # Arrange
    collection = FakeCollection([{"items": [], "total": 0}])

    # Act
    result = _search(collection, page=3, page_size=50)

    # Assert
    assert (result["page"], result["pageSize"]) == (3, 50)


def test_search_products_caps_server_side_execution_time():
    # Arrange
    collection = FakeCollection([{"items": [], "total": 0}])

    # Act
    _search(collection)

    # Assert
    assert collection.options == [{"maxTimeMS": QUERY_TIMEOUT_MS}]


def test_search_products_passes_criteria_as_first_pipeline_stage():
    # Arrange
    collection = FakeCollection([{"items": [], "total": 0}])
    criteria = {"category": "GPU"}

    # Act
    _search(collection, criteria=criteria)

    # Assert
    assert collection.pipelines[0][0] == {"$match": {"category": "GPU"}}
