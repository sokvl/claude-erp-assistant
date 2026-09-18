import pytest

from app.assistant.tools import (
    LIST_INVOICES_TOOL,
    PRODUCT_FACETS_TOOL,
    ListInvoicesInput,
    SearchProductsInput,
    build_search_products_tool,
    build_tools,
)
from app.catalog import vocab
from app.catalog.enums import SortField, SortOrder

VOCABULARIES = {
    "category": ["CPU", "GPU"],
    "brand": ["AMD", "NVIDIA"],
    "architecture": ["Hopper", "RDNA 3"],
    "memory_type": ["GDDR6", "HBM3"],
    "use_case": ["inference", "training"],
}

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


class FakeProducts:
    def __init__(self, values_by_path):
        self.values_by_path = values_by_path

    def distinct(self, path):
        return self.values_by_path[path]


@pytest.mark.parametrize("field", list(VOCABULARIES), ids=list(VOCABULARIES))
def test_build_search_products_tool_injects_vocabulary_as_enum(field):
    # Arrange / Act
    tool = build_search_products_tool(VOCABULARIES)

    # Assert
    assert _enum(_properties(tool)[field]) == VOCABULARIES[field]


@pytest.mark.parametrize("field", list(VOCABULARIES), ids=list(VOCABULARIES))
def test_build_search_products_tool_empty_vocabulary_omits_property(field):
    # Arrange
    vocabularies = {**VOCABULARIES, field: []}

    # Act
    tool = build_search_products_tool(vocabularies)

    # Assert
    assert field not in _properties(tool)


def test_build_search_products_tool_properties_match_search_input_fields():
    # Arrange / Act
    tool = build_search_products_tool(VOCABULARIES)

    # Assert
    assert list(_properties(tool)) == list(SearchProductsInput.model_fields)


def test_list_invoices_tool_properties_match_list_invoices_input_fields():
    # Arrange / Act
    properties = _properties(LIST_INVOICES_TOOL)

    # Assert
    assert list(properties) == list(ListInvoicesInput.model_fields)


@pytest.mark.parametrize(
    ("field", "enum_class"),
    [("sort_by", SortField), ("sort_order", SortOrder)],
    ids=["sort_by", "sort_order"],
)
def test_build_search_products_tool_static_enums_match_str_enums(field, enum_class):
    # Arrange / Act
    tool = build_search_products_tool(VOCABULARIES)

    # Assert
    assert _enum(_properties(tool)[field]) == [member.value for member in enum_class]


@pytest.mark.parametrize(
    "tool",
    [build_search_products_tool(VOCABULARIES), PRODUCT_FACETS_TOOL, LIST_INVOICES_TOOL],
    ids=["search_products", "get_product_facets", "list_invoices"],
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
    "tool_input",
    [
        {},
        {"category": "GPU", "brand": "NVIDIA", "architecture": "Hopper", "memory_type": "HBM3"},
        {"use_case": ["training", "inference"], "min_vram_gb": 80, "requires_pooling": True},
        {"min_fp16_tflops": 900.5, "min_price": 0, "max_price": 30000},
        {"sort_by": "fp16", "sort_order": "desc", "page": 2, "page_size": 25},
        {name: prop["default"] for name, prop in _properties(build_search_products_tool(VOCABULARIES)).items()
         if "default" in prop},
    ],
    ids=["empty", "vocabulary_values", "training_scenario", "price_and_fp16", "sorting_and_paging", "schema_defaults"],
)
def test_search_products_input_accepts_inputs_the_tool_schema_allows(tool_input):
    # Arrange
    properties = _properties(build_search_products_tool(VOCABULARIES))

    # Act
    params = SearchProductsInput.model_validate(tool_input)

    # Assert
    assert (set(tool_input) <= set(properties), params.page_size <= 25) == (True, True)


def test_search_products_input_accepts_every_enum_value_the_tool_schema_offers():
    # Arrange
    properties = _properties(build_search_products_tool(VOCABULARIES))
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


def test_build_tools_returns_tools_sorted_by_name_with_live_vocabulary():
    # Arrange
    products = FakeProducts({path: values for path, values in zip(vocab.VOCAB_FIELDS.values(), VOCABULARIES.values())})

    # Act
    tools = build_tools({"products": products})

    # Assert
    assert (
        [tool["name"] for tool in tools],
        tools[0] is PRODUCT_FACETS_TOOL,
        tools[1] is LIST_INVOICES_TOOL,
        _enum(_properties(tools[2])["brand"]),
    ) == (["get_product_facets", "list_invoices", "search_products"], True, True, ["AMD", "NVIDIA"])
