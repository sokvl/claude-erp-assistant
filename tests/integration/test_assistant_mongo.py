import json
from datetime import datetime

import pytest

from app.assistant.chat import TraceStep
from app.assistant.dispatch import HIDDEN_PRODUCT_FIELDS, ToolInputError, run_tool
from app.assistant.tools import SearchProductsInput, build_tools
from app.assistant.usage import USAGE_COLLECTION, record_usage
from app.catalog import vocab
from app.catalog.service import search_catalog

pytestmark = pytest.mark.integration

FIXTURE_INVOICES = [
    {
        "_id": invoice_id,
        "invoiceId": invoice_id,
        "customer": {"number": "0200769623", "name": "WAL-MAR corp"},
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


@pytest.mark.parametrize("param", list(vocab.VOCAB_FIELDS), ids=list(vocab.VOCAB_FIELDS))
def test_build_tools_enums_match_distinct_values_in_the_catalog(db, param):
    # Arrange
    expected = sorted(db["products"].distinct(vocab.VOCAB_FIELDS[param]))

    # Act
    properties = build_tools(db)[2]["input_schema"]["properties"]

    # Assert
    assert properties[param].get("items", properties[param])["enum"] == expected


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
    items = json.loads(run_tool(db, "list_invoices", {"page_size": 3}))["items"]

    # Assert
    assert [(sorted(item), sorted(item["dates"]), item["amounts"]) for item in items] == [
        (
            ["amounts", "currency", "customer", "dates", "invoiceId", "isOpen"],
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


def test_run_tool_value_missing_from_live_catalog_raises_tool_input_error(db):
    # Arrange / Act
    with pytest.raises(ToolInputError) as raised:
        run_tool(db, "search_products", {"architecture": "Blackwell"})

    # Assert
    assert "Unknown architecture: 'Blackwell'" in str(raised.value)


def test_recordUsage_realMongo_storesQueryableDocument(db):
    # Arrange
    steps = [TraceStep("model.call", "ok", 10, "stop=end_turn", {
        "input_tokens": 1000, "output_tokens": 100, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
    })]

    # Act
    record_usage(db, "conv-usage", steps, "done")

    # Assert
    stored = db[USAGE_COLLECTION].find_one({"conversationId": "conv-usage"}, {"_id": 0, "createdAt": 0})
    db[USAGE_COLLECTION].drop()
    assert (stored["tokens"]["input_tokens"], stored["modelCalls"], stored["costUsd"]) == (1000, 1, pytest.approx(0.0015))
