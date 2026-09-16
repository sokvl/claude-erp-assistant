import pytest

from app.catalog import vocab


class FakeCollection:
    def __init__(self, values):
        self.values = values
        self.calls = []

    def distinct(self, path):
        self.calls.append(path)
        return self.values


@pytest.fixture(autouse=True)
def _clear_cache():
    vocab.clear_cache()
    yield
    vocab.clear_cache()


@pytest.mark.parametrize(
    ("param", "expected_path"),
    [
        ("category", "category"),
        ("brand", "brand"),
        ("architecture", "specs.architecture"),
        ("memory_type", "specs.memoryType"),
        ("use_case", "specs.useCases"),
    ],
    ids=["category", "brand", "architecture", "memory_type", "use_case"],
)
def test_get_vocabulary_queries_mapped_document_path(param, expected_path):
    # Arrange
    collection = FakeCollection(["a", "b"])

    # Act
    result = vocab.get_vocabulary(collection, param)

    # Assert
    assert collection.calls == [expected_path]
    assert result == frozenset({"a", "b"})


def test_get_vocabulary_unknown_param_raises_key_error():
    # Arrange / Act / Assert
    with pytest.raises(KeyError):
        vocab.get_vocabulary(FakeCollection([]), "tier")


@pytest.mark.parametrize(
    ("elapsed", "expected_queries"),
    [
        (0, 1),
        (vocab.TTL_SECONDS - 1, 1),
        (vocab.TTL_SECONDS, 2),
        (vocab.TTL_SECONDS + 1, 2),
    ],
    ids=["immediate", "just_before_expiry", "at_expiry", "after_expiry"],
)
def test_get_vocabulary_requeries_only_once_ttl_has_elapsed(
    monkeypatch, elapsed, expected_queries
):
    # Arrange: advanced search is expected to be hot, so hits must not re-query
    collection = FakeCollection(["GPU"])
    clock = [0.0]
    monkeypatch.setattr(vocab.time, "monotonic", lambda: clock[0])
    vocab.get_vocabulary(collection, "category")

    # Act
    clock[0] = elapsed
    vocab.get_vocabulary(collection, "category")

    # Assert
    assert len(collection.calls) == expected_queries


def test_get_all_vocabularies_returns_sorted_values_for_every_field():
    # Arrange
    collection = FakeCollection(["b", "a"])

    # Act
    result = vocab.get_all_vocabularies(collection)

    # Assert
    assert result == {param: ["a", "b"] for param in vocab.VOCAB_FIELDS}
