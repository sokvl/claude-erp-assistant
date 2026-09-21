import pytest

from app.assistant.profiles import AssistantName
from app.assistant.tools import (
    ANALYZE_INVOICES_TOOL,
    CHART_INVOICES_TOOL,
    LIST_INVOICES_TOOL,
    PRODUCT_FACETS_TOOL,
    SEARCH_PRODUCTS_TOOL,
    TOOLS,
    ListInvoicesInput,
    SearchProductsInput,
)
from app.catalog.enums import Architecture, Brand, Category, MemoryType, SortField, SortOrder, UseCase
from app.invoices.enums import GroupBy, InvoiceSortField, InvoiceStatus
from app.invoices.schemas import InvoiceAnalyticsParams

STRICT_UNSUPPORTED_KEYWORDS = {
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
    "minLength", "maxLength", "maxItems", "uniqueItems", "title",
}


def _properties(tool):
    return tool["input_schema"]["properties"]


def _enum(prop):
    return prop.get("items", prop)["enum"]


def _walk(node, path="$"):
    if isinstance(node, dict):
        yield path, node
        for key, value in node.items():
            yield from _walk(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _walk(value, f"{path}[{index}]")


def test_search_products_tool_properties_match_search_input_fields():
    # Arrange / Act
    properties = _properties(SEARCH_PRODUCTS_TOOL)

    # Assert
    assert list(properties) == list(SearchProductsInput.model_fields)


@pytest.mark.parametrize(
    ("tool", "input_model"),
    [(LIST_INVOICES_TOOL, ListInvoicesInput), (ANALYZE_INVOICES_TOOL, InvoiceAnalyticsParams)],
    ids=["list_invoices", "analyze_invoices"],
)
def test_invoice_tool_properties_match_input_model_fields(tool, input_model):
    # Arrange / Act
    properties = _properties(tool)

    # Assert
    assert list(properties) == list(input_model.model_fields)


@pytest.mark.parametrize(
    ("tool", "field", "enum_class"),
    [
        (LIST_INVOICES_TOOL, "status", InvoiceStatus),
        (LIST_INVOICES_TOOL, "sort_by", InvoiceSortField),
        (LIST_INVOICES_TOOL, "sort_order", SortOrder),
        (ANALYZE_INVOICES_TOOL, "status", InvoiceStatus),
        (ANALYZE_INVOICES_TOOL, "group_by", GroupBy),
    ],
    ids=["list_status", "list_sort_by", "list_sort_order", "analyze_status", "analyze_group_by"],
)
def test_invoice_tool_static_enums_match_str_enums(tool, field, enum_class):
    # Arrange / Act
    prop = _properties(tool)[field]

    # Assert
    assert _enum(prop) == [member.value for member in enum_class]


@pytest.mark.parametrize(
    ("tool", "field"),
    [(tool, field) for tool in (LIST_INVOICES_TOOL, ANALYZE_INVOICES_TOOL) for field in ("posted_from", "posted_to", "as_of")],
    ids=[f"{tool}_{field}" for tool in ("list", "analyze") for field in ("posted_from", "posted_to", "as_of")],
)
def test_invoice_tool_date_fields_are_constrained_to_iso_dates(tool, field):
    # Arrange / Act
    prop = _properties(tool)[field]

    # Assert
    assert (prop["type"], prop["format"]) == ("string", "date")


@pytest.mark.parametrize(
    ("tool", "input_model"),
    [(LIST_INVOICES_TOOL, ListInvoicesInput), (ANALYZE_INVOICES_TOOL, InvoiceAnalyticsParams)],
    ids=["list_invoices", "analyze_invoices"],
)
def test_invoice_input_accepts_every_enum_value_and_default_the_tool_schema_offers(tool, input_model):
    # Arrange
    properties = _properties(tool)
    inputs = [{name: value} for name, prop in properties.items() if "enum" in prop for value in prop["enum"]]
    inputs.append({name: prop["default"] for name, prop in properties.items() if "default" in prop})

    # Act
    validated = [input_model.model_validate(tool_input) for tool_input in inputs]

    # Assert
    assert len(validated) == len(inputs)


@pytest.mark.parametrize(
    ("field", "enum_class"),
    [
        ("category", Category),
        ("brand", Brand),
        ("architecture", Architecture),
        ("memory_type", MemoryType),
        ("use_case", UseCase),
        ("sort_by", SortField),
        ("sort_order", SortOrder),
    ],
    ids=["category", "brand", "architecture", "memory_type", "use_case", "sort_by", "sort_order"],
)
def test_search_products_tool_enums_match_str_enums(field, enum_class):
    # Arrange / Act
    prop = _properties(SEARCH_PRODUCTS_TOOL)[field]

    # Assert
    assert _enum(prop) == [member.value for member in enum_class]


@pytest.mark.parametrize(
    "tool",
    [SEARCH_PRODUCTS_TOOL, PRODUCT_FACETS_TOOL],
    ids=["search_products", "get_product_facets"],
)
def test_tool_schema_uses_only_strict_supported_keywords(tool):
    # Arrange / Act
    nodes = list(_walk(tool["input_schema"]))

    # Assert
    assert (
        tool["strict"],
        [f"{path}.{key}" for path, node in nodes for key in node if key in STRICT_UNSUPPORTED_KEYWORDS],
        [path for path, node in nodes if node.get("type") == "object" and node.get("additionalProperties") is not False],
    ) == (True, [], [])


@pytest.mark.parametrize(
    "tool",
    [LIST_INVOICES_TOOL, ANALYZE_INVOICES_TOOL],
    ids=["list_invoices", "analyze_invoices"],
)
def test_invoice_tool_schema_is_not_strict_so_no_filter_is_silently_dropped(tool):
    # Arrange: strict decoding emits optional properties only in schema order, so a filter the model reaches
    # for after a later one is dropped without an error - live, Q1 dates vanished and all-time totals came back.
    # The required-and-nullable workaround needs 22 union parameters; the API allows 16. Pydantic validates instead.
    nodes = list(_walk(tool["input_schema"]))

    # Act
    open_objects = [path for path, node in nodes if node.get("type") == "object" and node.get("additionalProperties") is not False]

    # Assert
    assert ("strict" in tool, open_objects) == (False, [])


@pytest.mark.parametrize(
    "tool_input",
    [
        {},
        {"category": "GPU", "brand": "NVIDIA", "architecture": "Hopper", "memory_type": "HBM3"},
        {"use_case": ["training", "inference"], "min_vram_gb": 80, "requires_pooling": True},
        {"min_fp16_tflops": 900.5, "min_price": 0, "max_price": 30000},
        {"sort_by": "fp16", "sort_order": "desc", "page": 2, "page_size": 25},
        {name: prop["default"] for name, prop in _properties(SEARCH_PRODUCTS_TOOL).items() if "default" in prop},
    ],
    ids=["empty", "vocabulary_values", "training_scenario", "price_and_fp16", "sorting_and_paging", "schema_defaults"],
)
def test_search_products_input_accepts_inputs_the_tool_schema_allows(tool_input):
    # Arrange
    properties = _properties(SEARCH_PRODUCTS_TOOL)

    # Act
    params = SearchProductsInput.model_validate(tool_input)

    # Assert
    assert (set(tool_input) <= set(properties), params.page_size <= 25) == (True, True)


def test_search_products_input_accepts_every_enum_value_the_tool_schema_offers():
    # Arrange
    properties = _properties(SEARCH_PRODUCTS_TOOL)
    inputs = [
        {name: [value] if name == "use_case" else value}
        for name, prop in properties.items()
        if "enum" in prop.get("items", prop)
        for value in _enum(prop)
    ]

    # Act
    validated = [SearchProductsInput.model_validate(tool_input) for tool_input in inputs]

    # Assert
    assert len(validated) == len(inputs)


@pytest.mark.parametrize(
    ("assistant", "expected"),
    [
        (AssistantName.ADVISOR, [PRODUCT_FACETS_TOOL, SEARCH_PRODUCTS_TOOL]),
        (AssistantName.ANALYST, [ANALYZE_INVOICES_TOOL, CHART_INVOICES_TOOL, LIST_INVOICES_TOOL]),
        ("analyst", [ANALYZE_INVOICES_TOOL, CHART_INVOICES_TOOL, LIST_INVOICES_TOOL]),
    ],
    ids=["advisor", "analyst", "analyst_plain_string"],
)
def test_tools_each_assistant_gets_only_its_own_tools_sorted_by_name(assistant, expected):
    # Arrange / Act: a plain string must match too - an identity check once handed the analyst prompt the advisor's tools
    tools = TOOLS[assistant]

    # Assert
    assert tools == expected
