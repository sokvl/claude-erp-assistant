from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pymongo.database import Database

from app.catalog import vocab
from app.catalog.enums import SortField, SortOrder
from app.catalog.schemas import ProductSearchParams
from app.limits import (
    DEFAULT_TOOL_PAGE_SIZE,
    MAX_PAGE,
    MAX_PRICE,
    MAX_TFLOPS,
    MAX_TOOL_PAGE_SIZE,
    MAX_USE_CASES,
    MAX_VRAM_GB,
)

SEARCH_PRODUCTS = "search_products"
GET_PRODUCT_FACETS = "get_product_facets"
LIST_INVOICES = "list_invoices"


class SearchProductsInput(ProductSearchParams):
    page_size: int = Field(DEFAULT_TOOL_PAGE_SIZE, ge=1, le=MAX_TOOL_PAGE_SIZE)


class ListInvoicesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int = Field(1, ge=1, le=MAX_PAGE)
    page_size: int = Field(DEFAULT_TOOL_PAGE_SIZE, ge=1, le=MAX_TOOL_PAGE_SIZE)


SEARCH_PRODUCTS_DESCRIPTION = """
Search the hardware distributor's product catalog: GPUs, CPUs, RAM, storage, motherboards, PSUs, cases, cooling, monitors, networking and accessories. Returns {page, pageSize, total, items}; each item has sku, name, brand, category, listPrice (USD per unit) and, for GPUs only, a specs object (VRAM, memory type, FP16 throughput, TDP, interconnect, multi-GPU scaling, use cases, release year).

Use this for any question about which products exist, what they cost, how they compare, or which hardware fits a workload. Answer product questions from its results, never from memory. All filters are optional and combine with AND.

Map requests to filters:
- Memory needs ("at least 24 GB", "run a 13B model") -> min_vram_gb.
- Training, fine-tuning or inference workloads -> use_case, plus min_vram_gb for the model size.
- Budget ("under $2,000") -> max_price.
- "Fastest", "newest", "cheapest" -> sort_by with sort_order, not a threshold.
- A workload larger than any single card -> requires_pooling=true, and tell the user it needs several cards.

Do not:
- Guess values outside the listed enums; pick the matching value or omit the filter.
- Add category="GPU" when a GPU-only filter or sort is already set; those already restrict results to GPUs.
- Use this for invoices, customers, payments or stock levels; the catalog has none of that.
- Page through the catalog; narrow the filters instead.

If total is 0: relax the single most restrictive filter, search once more, and tell the user which constraint you relaxed. If that also returns nothing, say the catalog has no match."""

GET_PRODUCT_FACETS_DESCRIPTION = """List the values the product catalog currently offers: categories, brands, GPU architectures, GPU memory types and GPU use-case tags. Returns an object mapping each of those names to a sorted list.

Use this when the user asks what the catalog carries, e.g. "which brands do you sell?" or "what GPU architectures are available?".

Do not call it before a search: search_products already lists every allowed value in its schema."""

LIST_INVOICES_DESCRIPTION = """Return one page of accounts-receivable invoice records. Returns {page, pageSize, total, items}; each item has the invoice id, customer name and number, currency, open amount, open or cleared status, and posting, due and clear dates.

Use this only to show the user a sample of invoices or to browse a page they explicitly ask for.

Do not:
- Use it to find a specific invoice, a specific customer's invoices, open or overdue invoices, or totals. It has no filters and there are tens of thousands of records, so paging to find something is wrong. Tell the user that kind of lookup is not supported yet.
- Repeat customer names or amounts unless the user asked about those records.
- Use it for product or catalog questions; use search_products."""

_VOCAB_DESCRIPTIONS = {
    "category": "Product category. Omit when a GPU-only filter or sort is set; those already restrict results to GPUs.",
    "brand": "Manufacturer, exact spelling from the list. If the user names a brand that is not listed, the catalog does not carry it: say so instead of searching.",
    "architecture": "GPU microarchitecture. GPU-only.",
    "memory_type": "GPU memory technology. GPU-only.",
    "use_case": (
        "GPU workload tags; matches GPUs tagged with ANY listed value. Tags describe the kind of "
        f"workload, not model size - express size with min_vram_gb. At most {MAX_USE_CASES} values. GPU-only."
    ),
}


def _vocabulary_properties(vocabularies: Mapping[str, Sequence[str]]) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    for param in vocab.VOCAB_FIELDS:
        values = sorted(set(vocabularies[param]))
        if not values:
            continue
        schema: dict[str, Any] = {"type": "string", "enum": values}
        if param == "use_case":
            schema = {"type": "array", "items": schema}
        properties[param] = {**schema, "description": _VOCAB_DESCRIPTIONS[param]}
    return properties


def _search_properties() -> dict[str, Any]:
    fields = SearchProductsInput.model_fields
    return {
        "min_vram_gb": {
            "type": "integer",
            "description": (
                f"Minimum GPU memory in GB, 0-{MAX_VRAM_GB}. GPU-only. For an N-billion-parameter model: "
                "FP16 inference needs about 2N GB, LoRA fine-tuning about 2.5N GB, full training about 16N GB. "
                "State the estimate in your answer."
            ),
        },
        "max_vram_gb": {
            "type": "integer",
            "description": f"Maximum GPU memory in GB, 0-{MAX_VRAM_GB}, not below min_vram_gb. GPU-only. Set only when the user caps memory.",
        },
        "min_fp16_tflops": {
            "type": "number",
            "description": (
                f"Minimum dense FP16 tensor throughput in TFLOPS, 0-{MAX_TFLOPS:,.0f}. GPU-only. "
                "Use only for an explicit compute threshold; for 'fastest' sort by fp16 instead."
            ),
        },
        "min_price": {
            "type": "number",
            "description": f"Minimum unit list price in USD, 0-{MAX_PRICE:,.0f}.",
        },
        "max_price": {
            "type": "number",
            "description": f"Maximum unit list price in USD, 0-{MAX_PRICE:,.0f}, not below min_price. Use for budgets.",
        },
        "requires_pooling": {
            "type": "boolean",
            "description": (
                "true: only GPUs that scale across multiple cards (NVLink or equivalent). false: only GPUs that do not. "
                "Omit unless the user asks about multi-GPU setups or the memory need exceeds every single card. GPU-only."
            ),
        },
        "sort_by": {
            "type": "string",
            "enum": [member.value for member in SortField],
            "default": fields["sort_by"].default.value,
            "description": "price = list price, fp16 = compute throughput. Sorting by vram, fp16 or release_year drops non-GPU products.",
        },
        "sort_order": {
            "type": "string",
            "enum": [member.value for member in SortOrder],
            "default": fields["sort_order"].default.value,
            "description": "Use desc for largest, fastest, newest or most expensive first.",
        },
        "page": {
            "type": "integer",
            "default": fields["page"].default,
            "description": "1-based page number. Request another page only when the user wants more and total exceeds the results already shown.",
        },
        "page_size": {
            "type": "integer",
            "default": fields["page_size"].default,
            "description": f"Results per page, 1-{MAX_TOOL_PAGE_SIZE}.",
        },
    }


def build_search_products_tool(vocabularies: Mapping[str, Sequence[str]]) -> dict[str, Any]:
    return {
        "name": SEARCH_PRODUCTS,
        "description": SEARCH_PRODUCTS_DESCRIPTION,
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": _vocabulary_properties(vocabularies) | _search_properties(),
            "additionalProperties": False,
        },
    }


def build_product_facets_tool() -> dict[str, Any]:
    return {
        "name": GET_PRODUCT_FACETS,
        "description": GET_PRODUCT_FACETS_DESCRIPTION,
        "strict": True,
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    }


def build_list_invoices_tool() -> dict[str, Any]:
    fields = ListInvoicesInput.model_fields
    return {
        "name": LIST_INVOICES,
        "description": LIST_INVOICES_DESCRIPTION,
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "default": fields["page"].default,
                    "description": f"1-based page number, 1-{MAX_PAGE:,}.",
                },
                "page_size": {
                    "type": "integer",
                    "default": fields["page_size"].default,
                    "description": f"Invoices per page, 1-{MAX_TOOL_PAGE_SIZE}.",
                },
            },
            "additionalProperties": False,
        },
    }


def build_tools(db: Database) -> list[dict[str, Any]]:
    vocabularies = vocab.get_all_vocabularies(db["products"])
    return [
        build_product_facets_tool(),
        build_list_invoices_tool(),
        build_search_products_tool(vocabularies),
    ]
