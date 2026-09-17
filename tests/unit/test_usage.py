import logging

import pytest
from pymongo.errors import ServerSelectionTimeoutError

from app.assistant.chat import MODEL, TraceStep
from app.assistant.usage import USAGE_COLLECTION, cost_usd, record_usage, total_tokens

ZERO = {"input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}


def _call(input_tokens=0, output_tokens=0, cache_creation=0, cache_read=0):
    usage = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_creation_input_tokens": cache_creation,
        "cache_read_input_tokens": cache_read,
    }
    return TraceStep("model.call", "ok", 10, "stop=end_turn", usage)


class Collection:
    def __init__(self, error=None):
        self.documents = []
        self.error = error

    def insert_one(self, document):
        if self.error:
            raise self.error
        self.documents.append(document)


@pytest.mark.parametrize(
    ("steps", "expected"),
    [
        ([], ZERO),
        ([TraceStep("model.call", "retry", 5, "overloaded_error before any text")], ZERO),
        ([TraceStep("tool search_products", "ok", 1, "10 chars")], ZERO),
        ([_call(100, 20, 30, 40)], {**ZERO, "input_tokens": 100, "output_tokens": 20,
                                    "cache_creation_input_tokens": 30, "cache_read_input_tokens": 40}),
        ([_call(100, 20), TraceStep("tool search_products", "ok", 1, "10 chars"), _call(300, 50, cache_read=7)],
         {**ZERO, "input_tokens": 400, "output_tokens": 70, "cache_read_input_tokens": 7}),
    ],
    ids=["no_steps", "retry_without_usage", "tool_step", "single_call", "calls_around_tool"],
)
def test_totalTokens_steps_sumsOnlyModelUsage(steps, expected):
    # Arrange / Act
    result = total_tokens(steps)

    # Assert
    assert result == expected


@pytest.mark.parametrize(
    ("tokens", "expected"),
    [
        (ZERO, 0.0),
        ({**ZERO, "input_tokens": 1_000_000}, 1.00),
        ({**ZERO, "output_tokens": 1_000_000}, 5.00),
        ({**ZERO, "cache_creation_input_tokens": 1_000_000}, 1.25),
        ({**ZERO, "cache_read_input_tokens": 1_000_000}, 0.10),
        ({"input_tokens": 3574, "output_tokens": 115, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}, 0.004149),
    ],
    ids=["nothing", "input", "output", "cache_write", "cache_read", "typical_call"],
)
def test_costUsd_tokens_appliesModelPrices(tokens, expected):
    # Arrange / Act
    result = cost_usd(tokens, MODEL)

    # Assert
    assert result == pytest.approx(expected)


def test_recordUsage_turn_insertsTotalsAndCost():
    # Arrange
    collection = Collection()
    steps = [_call(1000, 100), TraceStep("tool search_products", "ok", 1, "10 chars"), _call(2000, 200)]

    # Act
    record_usage({USAGE_COLLECTION: collection}, "conv-1", steps, "done")

    # Assert
    [document] = collection.documents
    assert {key: value for key, value in document.items() if key != "createdAt"} == {
        "conversationId": "conv-1",
        "model": MODEL,
        "outcome": "done",
        "modelCalls": 2,
        "tokens": {**ZERO, "input_tokens": 3000, "output_tokens": 300},
        "costUsd": pytest.approx(0.0045),
    }


def test_recordUsage_databaseDown_logsInsteadOfRaising(caplog):
    # Arrange
    collection = Collection(ServerSelectionTimeoutError("down"))

    # Act
    with caplog.at_level(logging.ERROR, logger="app.assistant.usage"):
        record_usage({USAGE_COLLECTION: collection}, "conv-1", [_call(10, 1)], "done")

    # Assert
    assert "could not record token usage for conversation conv-1" in caplog.text
