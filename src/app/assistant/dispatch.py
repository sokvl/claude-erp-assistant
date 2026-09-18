import json
import logging
from typing import Any

from pydantic import ValidationError
from pymongo.database import Database

from app.assistant.tools import (
    ANALYZE_INVOICES,
    GET_PRODUCT_FACETS,
    LIST_INVOICES,
    SEARCH_PRODUCTS,
    ListInvoicesInput,
    SearchProductsInput,
)
from app.catalog import vocab
from app.catalog.service import search_catalog
from app.invoices.schemas import InvoiceAnalyticsParams
from app.invoices.service import analyze_invoices, list_invoices

HIDDEN_PRODUCT_FIELDS = frozenset({"_id", "tier"})


logger = logging.getLogger(__name__)


class ToolInputError(ValueError):
    pass


def run_tool(db: Database, name: str, tool_input: Any) -> str:
    logger.debug("tool %s called with %s", name, tool_input)
    try:
        result = _dispatch(db, name, tool_input)
    except ValidationError as exc:
        raise ToolInputError(_describe(exc)) from exc
    content = json.dumps(result, default=str, separators=(",", ":"), ensure_ascii=False)
    logger.debug("tool %s returned %s", name, content)
    return content


def _dispatch(db: Database, name: str, tool_input: Any) -> Any:
    if name == SEARCH_PRODUCTS:
        params = SearchProductsInput.model_validate(tool_input)
        result = search_catalog(db["products"], params)
        result["items"] = [
            {key: value for key, value in item.items() if key not in HIDDEN_PRODUCT_FIELDS}
            for item in result["items"]
        ]
        return result
    if name == GET_PRODUCT_FACETS:
        return vocab.get_all_vocabularies(db["products"])
    if name == LIST_INVOICES:
        return list_invoices(db["invoices"], ListInvoicesInput.model_validate(tool_input))
    if name == ANALYZE_INVOICES:
        return analyze_invoices(db["invoices"], InvoiceAnalyticsParams.model_validate(tool_input))
    raise ToolInputError(f"Unknown tool: {name}")


def _describe(exc: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(map(str, error['loc'])) or 'input'}: {error['msg']}"
        for error in exc.errors(include_url=False)
    )
