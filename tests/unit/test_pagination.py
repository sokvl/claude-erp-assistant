import pytest

from app.pagination import paginate


class FakeCollection:
    def __init__(self):
        self.find_args = None
        self.skip_by = None
        self.limit_to = None

    def find(self, query, projection):
        self.find_args = (query, projection)
        return self

    def skip(self, count):
        self.skip_by = count
        return self

    def limit(self, count):
        self.limit_to = count
        return self

    def __iter__(self):
        return iter([{"_id": "1"}])

    def estimated_document_count(self):
        return 42


@pytest.mark.parametrize(
    ("page", "page_size", "expected_skip"),
    [(1, 20, 0), (3, 10, 20), (100_000, 100, 9_999_900)],
    ids=["first_page", "third_page", "last_allowed_page"],
)
def test_paginate_skips_by_page_and_page_size(page, page_size, expected_skip):
    # Arrange
    collection = FakeCollection()

    # Act
    paginate(collection, page, page_size)

    # Assert
    assert (collection.skip_by, collection.limit_to) == (expected_skip, page_size)


@pytest.mark.parametrize(
    "projection",
    [None, {"_id": 0, "invoiceId": 1}],
    ids=["no_projection", "projection"],
)
def test_paginate_passes_empty_filter_and_projection_to_find(projection):
    # Arrange
    collection = FakeCollection()

    # Act
    paginate(collection, 1, 20, projection)

    # Assert
    assert collection.find_args == ({}, projection)


def test_paginate_returns_page_envelope():
    # Arrange / Act
    result = paginate(FakeCollection(), 2, 5)

    # Assert
    assert result == {"page": 2, "pageSize": 5, "total": 42, "items": [{"_id": "1"}]}
