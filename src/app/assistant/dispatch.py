import json
from typing import Any

from pydantic import ValidationError
from pymongo.database import Database

from app.assistant.tools import (
    GET_PRODUCT_FACETS,
    LIST_INVOICES,
    SEARCH_PRODUCTS,
    ListInvoicesInput,
    SearchProductsInput,
)
from app.catalog import vocab
from app.catalog.service import search_catalog
from app.pagination import paginate

HIDDEN_PRODUCT_FIELDS = frozenset({"_id", "tier"})

INVOICE_PROJECTION = {
    "_id": 0,
    "invoiceId": 1,
    "customer": 1,
    "currency": 1,
    "amounts.totalOpen": 1,
    "isOpen": 1,
    "dates.postingDate": 1,
    "dates.dueInDate": 1,
    "dates.clearDate": 1,
}


class ToolInputError(ValueError):
    pass


def run_tool(db: Database, name: str, tool_input: Any) -> str:
    try:
        result = _dispatch(db, name, tool_input)
    except ValidationError as exc:
        raise ToolInputError(_describe(exc)) from exc
    except vocab.UnknownVocabularyValue as exc:
        raise ToolInputError(f"{exc}. Call get_product_facets for allowed values.") from exc
    return json.dumps(result, default=str, separators=(",", ":"), ensure_ascii=False)


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
        params = ListInvoicesInput.model_validate(tool_input)
        return paginate(db["invoices"], params.page, params.page_size, INVOICE_PROJECTION)
    raise ToolInputError(f"Unknown tool: {name}")


def _describe(exc: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(map(str, error['loc'])) or 'input'}: {error['msg']}"
        for error in exc.errors(include_url=False)
    )
