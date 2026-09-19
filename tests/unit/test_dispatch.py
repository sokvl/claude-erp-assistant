import json
from datetime import datetime

import pytest

from app.assistant.dispatch import ToolInputError, run_tool

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
        self.aggregate_calls = []
        self.find_calls = []

    def aggregate(self, pipeline, **kwargs):
        self.aggregate_calls.append(pipeline)
        return iter([])

    def find(self, **kwargs):
        self.find_calls.append(kwargs)
        return iter([{"invoiceId": "1930438491", "dates": {"dueInDate": datetime(2020, 2, 10)}}])

    def count_documents(self, criteria, **kwargs):
        return 1

    def find_one(self, *args, **kwargs):
        return {"dates": {"postingDate": datetime(2019, 1, 2)}}


@pytest.fixture
def db():
    return {"products": FakeProducts(), "invoices": FakeInvoices()}


def test_run_tool_search_products_strips_internal_fields(db):
    # Arrange / Act
    result = json.loads(run_tool(db, "search_products", {"category": "GPU"}))

    # Assert
    assert result["items"] == [{"sku": "GPU-H100-80G", "listPrice": 27999.0}]


def test_run_tool_list_invoices_runs_the_filtered_page_query(db):
    # Arrange / Act
    run_tool(db, "list_invoices", {"status": "open", "page": 3, "page_size": 10})

    # Assert
    [find] = db["invoices"].find_calls
    assert (find["filter"], find["skip"], find["limit"]) == ({"isOpen": True}, 20, 10)


def test_run_tool_list_invoices_serializes_dates_as_strings(db):
    # Arrange / Act
    result = json.loads(run_tool(db, "list_invoices", {}))

    # Assert
    assert result["items"][0]["dates"]["dueInDate"] == "2020-02-10 00:00:00"


def test_run_tool_analyze_invoices_returns_figures_with_as_of_and_coverage(db):
    # Arrange / Act
    result = json.loads(run_tool(db, "analyze_invoices", {"group_by": "customer", "as_of": "2020-05-31"}))

    # Assert
    assert (result["asOf"], result["groupBy"], result["coverage"], len(db["invoices"].aggregate_calls)) == (
        "2020-05-31",
        "customer",
        {"firstPostingDate": "2019-01-02", "lastPostingDate": "2019-01-02"},
        1,
    )


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
        ("search_products", {"brand": "Nvidea"}, "brand: Input should be 'AMD', 'ASRock'"),
        ("search_products", {"use_case": ["mining"]}, "use_case.0: Input should be 'fine-tuning'"),
        ("list_invoices", {"page": 0}, "page: Input should be greater than or equal to 1"),
        ("list_invoices", {"page_size": 26}, "page_size: Input should be less than or equal to 25"),
        ("list_invoices", {"currency": "usd"}, "currency: String should match pattern"),
        ("analyze_invoices", {"group_by": "planet"}, "group_by: Input should be 'customer'"),
        ("analyze_invoices", {"posted_from": "2020-02-01", "posted_to": "2020-01-01"},
         "posted_from (2020-02-01) must not exceed posted_to (2020-01-01)"),
        ("analyze_invoices", {"posted_from": "last quarter"}, "posted_from: Input should be a valid date"),
        ("launch_rockets", {}, "Unknown tool: launch_rockets"),
    ],
    ids=["page_size_over_cap", "inverted_range", "invented_field", "unknown_brand",
         "unknown_use_case", "invoice_page_zero", "invoice_page_size_over_cap", "lowercase_currency",
         "unknown_group_by", "inverted_dates", "relative_date_text", "unknown_tool"],
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


@pytest.mark.parametrize(
    ("name", "tool_input"),
    [
        ("list_invoices", {"min_amount": 10, "max_amount": 1}),
        ("analyze_invoices", {"limit": 0}),
        ("analyze_invoices", {"as_of": "tomorrow"}),
    ],
    ids=["list_inverted_amounts", "analyze_zero_limit", "analyze_unparsable_as_of"],
)
def test_run_tool_invalid_invoice_input_never_queries_invoices(db, name, tool_input):
    # Arrange / Act
    with pytest.raises(ToolInputError):
        run_tool(db, name, tool_input)

    # Assert
    assert db["invoices"].aggregate_calls == []
