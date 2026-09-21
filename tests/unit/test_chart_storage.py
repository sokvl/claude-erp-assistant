from datetime import UTC, datetime, timedelta

import pytest
from pymongo.errors import ServerSelectionTimeoutError

from app.charts.schemas import ChartParams
from app.charts.storage import get_chart, recent_charts, save_chart
from app.limits import CHART_TTL_DAYS, MAX_CHART_BYTES

PARAMS = ChartParams.model_validate({"chart_type": "bar", "group_by": "customer", "metric": "open"})


class Collection:
    def __init__(self, documents=(), error=None):
        self.documents = list(documents)
        self.error = error
        self.find_calls = []

    def insert_one(self, document):
        if self.error:
            raise self.error
        self.documents.append(document)

    def find_one(self, criteria, **kwargs):
        return next((doc for doc in self.documents if doc["_id"] == criteria["_id"]), None)

    def find(self, criteria, projection, **kwargs):
        self.find_calls.append((criteria, projection, kwargs))
        return iter(self.documents)


def test_saveChart_image_storesMetadataAndBytesUnderANewId():
    # Arrange
    collection = Collection()

    # Act
    chart_id = save_chart(collection, "conv-1", PARAMS, "Open by customer", b"PNG")

    # Assert
    [document] = collection.documents
    assert document["_id"] == chart_id
    assert (document["conversationId"], document["title"]) == ("conv-1", "Open by customer")
    assert (document["chartType"], document["metric"], document["groupBy"]) == ("bar", "open", "customer")
    assert bytes(document["image"]) == b"PNG"


# Nothing else prunes the collection, so every chart must carry the expiry the
# TTL index in seed/indexes.py deletes on.
def test_saveChart_always_setsAnExpiryOneTtlAfterCreation():
    # Arrange
    collection = Collection()
    before = datetime.now(UTC)

    # Act
    save_chart(collection, "conv-1", PARAMS, "Open by customer", b"PNG")

    # Assert
    [document] = collection.documents
    assert document["expiresAt"] - document["createdAt"] == timedelta(days=CHART_TTL_DAYS)
    assert before <= document["createdAt"] <= datetime.now(UTC)


def test_saveChart_oversizedImage_isRejectedBeforeTheInsert():
    # Arrange
    collection = Collection()

    # Act
    with pytest.raises(ValueError, match="over the"):
        save_chart(collection, "conv-1", PARAMS, "Huge", b"x" * (MAX_CHART_BYTES + 1))

    # Assert
    assert collection.documents == []


# record_usage swallows a failed insert because usage is bookkeeping; a chart the
# answer points at is not, so the error must reach the caller.
def test_saveChart_databaseError_propagates():
    # Arrange
    collection = Collection(error=ServerSelectionTimeoutError("no primary"))

    # Act / Assert
    with pytest.raises(ServerSelectionTimeoutError):
        save_chart(collection, "conv-1", PARAMS, "Open by customer", b"PNG")


def test_getChart_knownId_returnsTheStoredDocument():
    # Arrange
    collection = Collection()
    chart_id = save_chart(collection, "conv-1", PARAMS, "Open by customer", b"PNG")

    # Act / Assert
    assert get_chart(collection, chart_id)["title"] == "Open by customer"
    assert get_chart(collection, "missing") is None


def test_recentCharts_conversation_queriesNewestFirstWithoutTheImage():
    # Arrange
    collection = Collection()

    # Act
    recent_charts(collection, "conv-1", 5)

    # Assert
    [(criteria, projection, kwargs)] = collection.find_calls
    assert criteria == {"conversationId": "conv-1"}
    assert projection == {"image": 0}
    assert (kwargs["sort"], kwargs["limit"]) == ([("createdAt", -1)], 5)
