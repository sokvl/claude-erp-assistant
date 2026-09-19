import json
from datetime import datetime

import pytest

from app.assistant.chat import TraceStep
from app.assistant.dispatch import HIDDEN_PRODUCT_FIELDS, run_tool
from app.assistant.profiles import ADVISOR
from app.assistant.tools import SearchProductsInput
from app.assistant.usage import USAGE_COLLECTION, record_usage
from app.catalog import vocab
from app.catalog.service import search_catalog

pytestmark = pytest.mark.integration

FIXTURE_INVOICES = [
    {
        "_id": invoice_id,
        "invoiceId": invoice_id,
        "customer": {"number": "0200769623", "name": "WAL-MAR corp", "nameLower": "wal-mar corp"},
        "currency": "USD",
        "amounts": {"totalOpen": total},
        "isOpen": is_open,
        "paymentTerms": "NAH4",
        "dates": {
            "postingDate": datetime(2020, 1, 26),
            "dueInDate": datetime(2020, 2, 10),
            "clearDate": None if is_open else datetime(2020, 2, 11),
            "baselineCreateDate": datetime(2020, 1, 26),
        },
    }
    for invoice_id, total, is_open in [("INV-1", 54273.28, False), ("INV-2", 1250.0, True), ("INV-3", 99.5, True)]
]


@pytest.fixture(scope="module")
def db(products):
    database = products.database
    database["invoices"].insert_many(FIXTURE_INVOICES)
    yield database
    database["invoices"].drop()


def _json_roundtrip(value):
    return json.loads(json.dumps(value, default=str))


@pytest.mark.parametrize(
    ("tool_input", "expected_count"),
    [
        ({}, 7),
        ({"min_vram_gb": 80}, 2),
        ({"brand": "AMD"}, 3),
        ({"use_case": ["training"], "requires_pooling": True}, 2),
        ({"sort_by": "vram", "sort_order": "desc", "page_size": 2}, 2),
        ({"max_price": 1000}, 3),
    ],
    ids=["no_filters", "min_vram", "brand", "training_scenario", "sorted_page", "budget"],
)
def test_run_tool_search_products_matches_direct_catalog_search(db, tool_input, expected_count):
    # Arrange
    direct = search_catalog(db["products"], SearchProductsInput.model_validate(tool_input))
    direct["items"] = [
        {key: value for key, value in item.items() if key not in HIDDEN_PRODUCT_FIELDS} for item in direct["items"]
    ]

    # Act
    result = json.loads(run_tool(db, "search_products", tool_input))

    # Assert
    assert (result == _json_roundtrip(direct), len(result["items"])) == (True, expected_count)


def test_run_tool_search_products_never_exposes_internal_fields(db):
    # Arrange / Act
    items = json.loads(run_tool(db, "search_products", {}))["items"]

    # Assert
    assert [sorted(HIDDEN_PRODUCT_FIELDS & item.keys()) for item in items] == [[] for _ in items]


def test_run_tool_list_invoices_returns_only_projected_fields(db):
    # Arrange / Act
    items = json.loads(run_tool(db, "list_invoices", {"page_size": 3, "sort_order": "asc"}))["items"]

    # Assert
    assert [(sorted(item), sorted(item["customer"]), sorted(item["dates"]), item["amounts"]) for item in items] == [
        (
            ["amounts", "currency", "customer", "dates", "invoiceId", "isOpen"],
            ["name", "number"],
            ["clearDate", "dueInDate", "postingDate"],
            {"totalOpen": invoice["amounts"]["totalOpen"]},
        )
        for invoice in FIXTURE_INVOICES
    ]


def test_run_tool_get_product_facets_matches_live_vocabularies(db):
    # Arrange
    expected = vocab.get_all_vocabularies(db["products"])

    # Act
    result = json.loads(run_tool(db, "get_product_facets", {}))

    # Assert
    assert result == expected


def test_recordUsage_realMongo_storesQueryableDocument(db):
    # Arrange
    steps = [TraceStep("model.call", "ok", 10, "stop=end_turn", {
        "input_tokens": 1000, "output_tokens": 100, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
    })]

    # Act
    record_usage(db, "conv-usage", ADVISOR, steps, "done")

    # Assert
    stored = db[USAGE_COLLECTION].find_one({"conversationId": "conv-usage"}, {"_id": 0, "createdAt": 0})
    db[USAGE_COLLECTION].drop()
    assert (stored["tokens"]["input_tokens"], stored["modelCalls"], stored["costUsd"]) == (1000, 1, pytest.approx(0.0015))
