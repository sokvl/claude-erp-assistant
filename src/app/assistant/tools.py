from collections.abc import Mapping
from typing import Any

from pydantic import Field

from app.assistant.profiles import AssistantName
from app.catalog.enums import Architecture, Brand, Category, MemoryType, SortField, SortOrder, UseCase
from app.catalog.schemas import ProductSearchParams
from app.invoices.enums import GroupBy, InvoiceSortField, InvoiceStatus
from app.invoices.schemas import InvoiceListParams
from app.limits import (
    DEFAULT_ANALYTICS_ROWS,
    DEFAULT_TOOL_PAGE_SIZE,
    MAX_AMOUNT,
    MAX_ANALYTICS_ROWS,
    MAX_PAGE,
    MAX_PRICE,
    MAX_TEXT_LENGTH,
    MAX_TFLOPS,
    MAX_TOOL_PAGE_SIZE,
    MAX_USE_CASES,
    MAX_VRAM_GB,
)

SEARCH_PRODUCTS = "search_products"
GET_PRODUCT_FACETS = "get_product_facets"
LIST_INVOICES = "list_invoices"
ANALYZE_INVOICES = "analyze_invoices"


class SearchProductsInput(ProductSearchParams):
    page_size: int = Field(DEFAULT_TOOL_PAGE_SIZE, ge=1, le=MAX_TOOL_PAGE_SIZE)


class ListInvoicesInput(InvoiceListParams):
    page_size: int = Field(DEFAULT_TOOL_PAGE_SIZE, ge=1, le=MAX_TOOL_PAGE_SIZE)


SEARCH_PRODUCTS_DESCRIPTION = """
Search the hardware distributor's product catalog: GPUs, CPUs, RAM, storage, motherboards, PSUs, cases, cooling, monitors, networking and accessories. Returns {page, pageSize, total, items}; each item has sku, name, brand, category, listPrice (USD per unit) and, for GPUs only, a specs object (VRAM, memory type, FP16 throughput, TDP, interconnect, multi-GPU scaling, use cases, release year).

Use this for any question about which products exist, what they cost, how they compare, or which hardware fits a workload. Answer product questions from its results, never from memory. All filters are optional and combine with AND.

Map requests to filters:
- A product type ("GPUs", "CPUs", "monitors") -> category. A brand alone spans every category, so "AMD GPUs" needs brand="AMD" and category="GPU".
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

LIST_INVOICES_DESCRIPTION = """Find individual accounts-receivable invoices. Returns {page, pageSize, total, items}; total counts every invoice matching the filters, and each item has invoiceId, customer (number and name), currency, amounts.totalOpen (the invoice amount), isOpen, and posting, due and clear dates.

Use this to show specific invoices: a customer's open invoices, the largest invoices of a period, the newest invoices, or the invoices behind a figure from analyze_invoices. All filters are optional and combine with AND. To count matching invoices, read total.

Do not:
- Page through invoices to add up, average or rank them; use analyze_invoices for any total, average, ranking or trend.
- Use it for product or catalog questions."""

ANALYZE_INVOICES_DESCRIPTION = f"""Compute invoice figures in the database. Returns {{asOf, groupBy, filters, coverage, currencies}}. filters echoes the filters that were applied; state the period and filters from it. coverage gives the first and last posting date in the whole data set, not in the result. currencies has one entry per invoice currency with groupCount (number of groups) and rows. Every row has invoiceCount, totalAmount, averageAmount (per invoice), openAmount (unpaid), overdueAmount (unpaid and due before asOf) and averageDaysToPay (posting to payment, paid invoices only). Amounts are in that entry's currency, rounded to cents.

Without group_by each currency has one row with its totals. With group_by the rows are:
- customer: one row per customer number (key) with a customer name (label), largest totalAmount first.
- product, brand, category: built from invoice lines; totalAmount is the value of those lines and units the quantity sold. Product rows add the product name (label) and averageUnitPrice. Largest totalAmount first.
- month, quarter, year: one row per period of posting date, key = first day of the period, oldest first.

Map requests to parameters:
- A period ("Q1 2020", "in 2019", "last month") -> posted_from and posted_to.
- "Top N", "largest", "best-selling" -> group_by with limit=N.
- "Trend", "per month", "by quarter" -> group_by=month, quarter or year.
- Outstanding or overdue money -> openAmount and overdueAmount; set as_of when the user names a reference date.

Rankings return {DEFAULT_ANALYTICS_ROWS} rows per currency unless limit is set, periods up to {MAX_ANALYTICS_ROWS}. If groupCount is larger than the number of rows, the list was cut.

Do not:
- Add, compare or rank amounts across currencies; every currency is reported separately.
- Use it for product or catalog questions."""

def _search_properties() -> dict[str, Any]:
    fields = SearchProductsInput.model_fields
    return {
        "category": {
            "type": "string",
            "enum": [member.value for member in Category],
            "description": (
                "Product category. Set it whenever the user names a product type, including together with a brand. "
                "Omit it only when a GPU-only filter or sort is set; those already restrict results to GPUs."
            ),
        },
        "brand": {
            "type": "string",
            "enum": [member.value for member in Brand],
            "description": "Manufacturer, exact spelling from the list. If the user names a brand that is not listed, the catalog does not carry it: say so instead of searching.",
        },
        "architecture": {
            "type": "string",
            "enum": [member.value for member in Architecture],
            "description": "GPU microarchitecture. GPU-only.",
        },
        "memory_type": {
            "type": "string",
            "enum": [member.value for member in MemoryType],
            "description": "GPU memory technology. GPU-only.",
        },
        "use_case": {
            "type": "array",
            "items": {"type": "string", "enum": [member.value for member in UseCase]},
            "description": (
                "GPU workload tags; matches GPUs tagged with ANY listed value. Tags describe the kind of "
                f"workload, not model size - express size with min_vram_gb. At most {MAX_USE_CASES} values. GPU-only."
            ),
        },
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


SEARCH_PRODUCTS_TOOL: dict[str, Any] = {
    "name": SEARCH_PRODUCTS,
    "description": SEARCH_PRODUCTS_DESCRIPTION,
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": _search_properties(),
        "additionalProperties": False,
    },
}


PRODUCT_FACETS_TOOL: dict[str, Any] = {
    "name": GET_PRODUCT_FACETS,
    "description": GET_PRODUCT_FACETS_DESCRIPTION,
    "strict": True,
    "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
}

def _invoice_filter_properties() -> dict[str, Any]:
    return {
        "posted_from": {
            "type": "string",
            "format": "date",
            "description": "First posting date to include, YYYY-MM-DD.",
        },
        "posted_to": {
            "type": "string",
            "format": "date",
            "description": "Last posting date to include, YYYY-MM-DD, not before posted_from.",
        },
        "customer": {
            "type": "string",
            "description": (
                f"Customer number (exact) or part of the customer name (any case), at most {MAX_TEXT_LENGTH} characters. "
                "Names vary between invoices of the same customer, so a name part can match several customer numbers."
            ),
        },
        "currency": {
            "type": "string",
            "description": "Invoice currency as a 3-letter ISO code, e.g. USD or CAD.",
        },
        "status": {
            "type": "string",
            "enum": [member.value for member in InvoiceStatus],
            "description": "open = not paid yet, cleared = paid, overdue = not paid and due before as_of.",
        },
        "min_amount": {
            "type": "number",
            "description": f"Minimum invoice amount in the invoice currency, 0-{MAX_AMOUNT:,.0f}.",
        },
        "max_amount": {
            "type": "number",
            "description": f"Maximum invoice amount in the invoice currency, 0-{MAX_AMOUNT:,.0f}, not below min_amount.",
        },
        "as_of": {
            "type": "string",
            "format": "date",
            "description": "Reference date for overdue, YYYY-MM-DD. Defaults to today; set it only when the user names a date.",
        },
    }


def _list_invoices_properties() -> dict[str, Any]:
    fields = ListInvoicesInput.model_fields
    return _invoice_filter_properties() | {
        "sort_by": {
            "type": "string",
            "enum": [member.value for member in InvoiceSortField],
            "default": fields["sort_by"].default.value,
            "description": "posting_date or amount (the invoice amount).",
        },
        "sort_order": {
            "type": "string",
            "enum": [member.value for member in SortOrder],
            "default": fields["sort_order"].default.value,
            "description": "desc for newest or largest first.",
        },
        "page": {
            "type": "integer",
            "default": fields["page"].default,
            "description": f"1-based page number, 1-{MAX_PAGE:,}. Request another page only when the user wants more.",
        },
        "page_size": {
            "type": "integer",
            "default": fields["page_size"].default,
            "description": f"Invoices per page, 1-{MAX_TOOL_PAGE_SIZE}.",
        },
    }


def _analyze_invoices_properties() -> dict[str, Any]:
    return _invoice_filter_properties() | {
        "group_by": {
            "type": "string",
            "enum": [member.value for member in GroupBy],
            "description": "Omit for totals per currency.",
        },
        "limit": {
            "type": "integer",
            "description": f"Rows per currency, 1-{MAX_ANALYTICS_ROWS}. Set it for top-N requests.",
        },
    }


def _invoice_tool(name: str, description: str, properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "input_schema": {"type": "object", "properties": properties, "additionalProperties": False},
    }


LIST_INVOICES_TOOL = _invoice_tool(LIST_INVOICES, LIST_INVOICES_DESCRIPTION, _list_invoices_properties())
ANALYZE_INVOICES_TOOL = _invoice_tool(ANALYZE_INVOICES, ANALYZE_INVOICES_DESCRIPTION, _analyze_invoices_properties())


TOOLS: Mapping[AssistantName, list[dict[str, Any]]] = {
    AssistantName.ADVISOR: [PRODUCT_FACETS_TOOL, SEARCH_PRODUCTS_TOOL],
    AssistantName.ANALYST: [ANALYZE_INVOICES_TOOL, LIST_INVOICES_TOOL],
}
