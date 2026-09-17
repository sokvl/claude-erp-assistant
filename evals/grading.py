import json
import re
from typing import Any

from app.assistant.dispatch import INVOICE_PROJECTION
from app.assistant.prompts import OUT_OF_SCOPE_REPLY
from app.assistant.tools import LIST_INVOICES, SEARCH_PRODUCTS, ListInvoicesInput
from app.catalog.schemas import ProductSearchParams
from app.catalog.service import search_catalog
from app.limits import MAX_PAGE_SIZE
from app.pagination import paginate
from cases import Case, Gold

TABLE = re.compile(r"^\s*\|.*\|\s*\n\s*\|[\s:|-]*-{3,}", re.MULTILINE)
SKU = re.compile(r"\b[A-Z][A-Z0-9]{1,5}(?:-[A-Z0-9]+)+\b")
ROW_TOOLS = (SEARCH_PRODUCTS, LIST_INVOICES)


def query_ids(db: Any, tool: str, params: dict[str, Any], expand: bool) -> frozenset[str]:
    if tool == LIST_INVOICES:
        query = ListInvoicesInput.model_validate(params)
        items = paginate(db["invoices"], query.page, query.page_size, INVOICE_PROJECTION)["items"]
        return frozenset(item["invoiceId"] for item in items)
    paging = {"page": 1, "page_size": MAX_PAGE_SIZE} if expand else {}
    items = search_catalog(db["products"], ProductSearchParams.model_validate({**params, **paging}))["items"]
    return frozenset(item["sku"] for item in items)


def gold_ids(db: Any, gold: Gold) -> frozenset[str]:
    return query_ids(db, gold.tool, gold.params, expand="page_size" not in gold.params)


def output_ids(call: dict[str, Any]) -> frozenset[str]:
    key = "invoiceId" if call["name"] == LIST_INVOICES else "sku"
    return frozenset(item[key] for item in json.loads(call["output"]).get("items", []))


def matches(rule: str, actual: frozenset[str], expected: frozenset[str]) -> bool:
    return actual == expected if rule == "equal" else expected <= actual


def grade(
    case: Case,
    db: Any,
    catalog: dict[str, dict[str, Any]],
    answer: str,
    calls: list[dict[str, Any]],
    final: bool,
) -> list[str]:
    names = [call["name"] for call in calls]
    refused = answer.strip() == OUT_OF_SCOPE_REPLY
    if case.refusal:
        return [f"[scope] called {names} instead of refusing"] * bool(calls) + [
            f"[scope] expected the exact refusal, got {answer[:160]!r}"
        ] * (not refused)

    failures = ["[scope] refused an in-scope question"] * refused
    if not set(names) & set(case.tools):
        failures.append(f"[retrieval] expected one of {list(case.tools)}, called {names}")
    failures += [f"[tool] {call['name']} {call['input']} rejected: {call['error']}" for call in calls if "error" in call]
    if case.gold:
        failures += _grade_asked(db, case.gold, calls)
    if not final:
        return failures

    returned = [call for call in calls if "output" in call and call["name"] in ROW_TOOLS]
    failures += [
        f"[tool] {call['name']} {call['input']} output differs from re-running it against MongoDB"
        for call in returned
        if query_ids(db, call["name"], call["input"], expand=False) != output_ids(call)
    ]
    if case.table and not TABLE.search(answer):
        failures.append("[format] expected a markdown table")

    prefixes = {sku.split("-")[0] for sku in catalog}
    mentioned = {token for token in SKU.findall(answer) if token.split("-")[0] in prefixes}
    known = frozenset(mentioned & catalog.keys())
    received = frozenset().union(*(output_ids(call) for call in returned if call["name"] == SEARCH_PRODUCTS))
    if mentioned - known:
        failures.append(f"[grounding] SKUs not in the catalog: {sorted(mentioned - known)}")
    if known - received:
        failures.append(f"[grounding] SKUs never returned by a search this turn: {sorted(known - received)}")
    failures += [
        f"[grounding] {sku}: list price {catalog[sku]['listPrice']:,.2f} not stated"
        for sku in sorted(known)
        if not _price_stated(catalog[sku]["listPrice"], answer)
    ]
    if case.max_price is not None and (over := sorted(s for s in known if catalog[s]["listPrice"] > case.max_price)):
        failures.append(f"[retrieval] over the {case.max_price:,.0f} budget: {over}")
    if case.gold and case.gold.answer and not matches(case.gold.answer, known, expected := gold_ids(db, case.gold)):
        failures.append(f"[answer] mentioned {sorted(known)}, gold ({case.gold.answer}) is {sorted(expected)}")
    return failures


def _grade_asked(db: Any, gold: Gold, calls: list[dict[str, Any]]) -> list[str]:
    expected = gold_ids(db, gold)
    attempts, combined = [], frozenset()
    for call in (call for call in calls if call["name"] == gold.tool):
        if "error" in call:
            attempts.append(f"{call['input']} -> rejected")
            continue
        asked = query_ids(db, gold.tool, call["input"], expand=gold.tool == SEARCH_PRODUCTS)
        if matches(gold.results, asked, expected):
            return []
        combined |= asked
        attempts.append(f"{call['input']} -> {sorted(asked)}")
    if len(attempts) > 1 and matches(gold.results, combined, expected):
        return []
    return [f"[retrieval] gold {gold.params} ({gold.results}) -> {sorted(expected)}; asked: {'; '.join(attempts) or 'nothing'}"]


def _price_stated(price: float, answer: str) -> bool:
    plain = answer.replace(",", "")
    return f"{price:.0f}" in plain or f"{price:.2f}" in plain
