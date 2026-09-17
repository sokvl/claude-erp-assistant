import json
from datetime import datetime

import pytest

from app.assistant.dispatch import INVOICE_PROJECTION, ToolInputError, run_tool
from app.catalog import vocab

VOCABULARIES = {
    "category": ["GPU", "CPU"],
    "brand": ["NVIDIA", "AMD"],
    "specs.architecture": ["Hopper"],
    "specs.memoryType": ["HBM3"],
    "specs.useCases": ["training", "inference"],
}


class FakeProducts:
    def __init__(self):
        self.aggregate_calls = []

    def distinct(self, path):
        return VOCABULARIES[path]

    def aggregate(self, pipeline, **kwargs):
        self.aggregate_calls.append(pipeline)
        return iter([{
            "items": [{"_id": "GPU-H100-80G", "sku": "GPU-H100-80G", "tier": "enterprise", "listPrice": 27999.0}],
            "total": 1,
        }])


class FakeInvoices:
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
        return iter([{"invoiceId": "1930438491", "dates": {"dueInDate": datetime(2020, 2, 10)}}])

    def estimated_document_count(self):
        return 48839


@pytest.fixture(autouse=True)
def _clear_vocabulary_cache():
    vocab.clear_cache()
    yield
    vocab.clear_cache()


@pytest.fixture
def db():
    return {"products": FakeProducts(), "invoices": FakeInvoices()}


def test_run_tool_search_products_strips_internal_fields(db):
    # Arrange / Act
    result = json.loads(run_tool(db, "search_products", {"category": "GPU"}))

    # Assert
    assert result["items"] == [{"sku": "GPU-H100-80G", "listPrice": 27999.0}]


def test_run_tool_list_invoices_reads_only_projected_fields(db):
    # Arrange / Act
    run_tool(db, "list_invoices", {"page": 3, "page_size": 10})

    # Assert
    assert (db["invoices"].find_args, db["invoices"].skip_by, db["invoices"].limit_to) == (
        ({}, INVOICE_PROJECTION),
        20,
        10,
    )


def test_run_tool_list_invoices_serializes_dates_as_strings(db):
    # Arrange / Act
    result = json.loads(run_tool(db, "list_invoices", {}))

    # Assert
    assert result["items"][0]["dates"]["dueInDate"] == "2020-02-10 00:00:00"


def test_run_tool_get_product_facets_returns_sorted_vocabularies(db):
    # Arrange / Act
    result = json.loads(run_tool(db, "get_product_facets", {}))

    # Assert
    assert result == {
        "category": ["CPU", "GPU"],
        "brand": ["AMD", "NVIDIA"],
        "architecture": ["Hopper"],
        "memory_type": ["HBM3"],
        "use_case": ["inference", "training"],
    }


@pytest.mark.parametrize(
    ("name", "tool_input", "expected_message"),
    [
        ("search_products", {"page_size": 26}, "page_size: Input should be less than or equal to 25"),
        ("search_products", {"min_vram_gb": 80, "max_vram_gb": 8}, "min_vram_gb (80) must not exceed max_vram_gb (8)"),
        ("search_products", {"in_stock": True}, "in_stock: Extra inputs are not permitted"),
        ("search_products", {"brand": "Nvidea"}, "Unknown brand: 'Nvidea'. Call get_product_facets for allowed values."),
        ("search_products", {"use_case": ["mining"]}, "Unknown use_case: 'mining'"),
        ("list_invoices", {"page": 0}, "page: Input should be greater than or equal to 1"),
        ("launch_rockets", {}, "Unknown tool: launch_rockets"),
    ],
    ids=["page_size_over_cap", "inverted_range", "invented_field", "unknown_brand",
         "unknown_use_case", "invoice_page_zero", "unknown_tool"],
)
def test_run_tool_invalid_input_raises_readable_tool_input_error(db, name, tool_input, expected_message):
    # Arrange / Act
    with pytest.raises(ToolInputError) as raised:
        run_tool(db, name, tool_input)

    # Assert
    assert expected_message in str(raised.value)


@pytest.mark.parametrize(
    "tool_input",
    [{"page_size": 26}, {"brand": "Nvidea"}, {"min_vram_gb": 80, "max_vram_gb": 8}],
    ids=["validation_error", "unknown_vocabulary", "inverted_range"],
)
def test_run_tool_invalid_search_input_never_queries_products(db, tool_input):
    # Arrange / Act
    with pytest.raises(ToolInputError):
        run_tool(db, "search_products", tool_input)

    # Assert
    assert db["products"].aggregate_calls == []
