from app.catalog import vocab


class FakeCollection:
    def __init__(self, values):
        self.values = values
        self.calls = []

    def distinct(self, path):
        self.calls.append(path)
        return self.values


def test_get_all_vocabularies_queries_each_mapped_document_path():
    # Arrange
    collection = FakeCollection(["a"])

    # Act
    vocab.get_all_vocabularies(collection)

    # Assert
    assert collection.calls == [
        "category", "brand", "specs.architecture", "specs.memoryType", "specs.useCases",
    ]


def test_get_all_vocabularies_returns_sorted_values_for_every_field():
    # Arrange
    collection = FakeCollection(["b", "a"])

    # Act
    result = vocab.get_all_vocabularies(collection)

    # Assert
    assert result == {param: ["a", "b"] for param in vocab.VOCAB_FIELDS}
