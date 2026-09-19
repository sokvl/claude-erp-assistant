from datetime import date, datetime, timedelta
from uuid import uuid4

import pytest
from indexes import INVOICE_INDEXES, sync_indexes

from app.catalog.enums import SortField, SortOrder
from app.catalog.query import build_product_filter, build_search_pipeline
from app.invoices.query import build_analytics_pipeline, build_invoice_filter, build_list_query
from app.invoices.schemas import InvoiceAnalyticsParams, InvoiceFilter, InvoiceListParams

pytestmark = pytest.mark.integration

AS_OF = date(2021, 1, 1)
PAGE_SIZE = 10
CUSTOMERS = 40
MARCH_2019 = {"posted_from": date(2019, 3, 1), "posted_to": date(2019, 3, 31)}

POSTING = "dates.postingDate_1__id_1"
STATUS = "isOpen_1_dates.postingDate_1__id_1"
AMOUNT = "amounts.totalOpen_1__id_1"
INTERSECTIONS = {"AND_HASH", "AND_SORTED"}


def _invoice(i):
    # One invoice a day through Feb 2020; every 5th is open (so overdue on AS_OF), every 10th a CAD one.
    # 40 customers, each under three name spellings that share their first word, as in the real data.
    posted = datetime(2019, 1, 1) + timedelta(days=i)
    is_open = i % 5 == 0
    name = f"CUST{i % CUSTOMERS:02d} {('corp', 'llc', 'inc')[i % 3]}"
    return {
        "_id": f"INV{i:04d}",
        "invoiceId": f"INV{i:04d}",
        "customer": {"number": f"{i % CUSTOMERS:04d}", "name": name, "nameLower": name.lower()},
        "currency": "CAD" if i % 10 == 3 else "USD",
        "amounts": {"totalOpen": float(i * 7919 % 100_000)},
        "isOpen": is_open,
        "dates": {
            "postingDate": posted,
            "dueInDate": posted + timedelta(days=30),
            "clearDate": None if is_open else posted + timedelta(days=20),
        },
    }


@pytest.fixture(scope="module")
def invoice_db(mongo_client):
    # Arrange: a throwaway database, never the demo data in invoices_db
    db_name = f"test_invoices_{uuid4().hex[:8]}"
    database = mongo_client[db_name]
    database["invoices"].insert_many([_invoice(i) for i in range(400)])
    sync_indexes(database["invoices"], INVOICE_INDEXES)

    yield database

    # Annihilate
    mongo_client.drop_database(db_name)


def _list(**params):
    p = InvoiceListParams(as_of=AS_OF, page_size=PAGE_SIZE, **params)
    query = build_list_query(
        criteria=build_invoice_filter(p, AS_OF), sort_by=p.sort_by, order=p.sort_order, page=p.page, page_size=p.page_size
    )
    return {
        "find": "invoices", "filter": query["filter"], "projection": query["projection"],
        "sort": dict(query["sort"]), "skip": query["skip"], "limit": query["limit"],
    }


def _count(**params):
    # the pipeline pymongo's count_documents sends
    criteria = build_invoice_filter(InvoiceListParams(as_of=AS_OF, **params), AS_OF)
    return {"aggregate": "invoices", "pipeline": [{"$match": criteria}, {"$group": {"_id": 1, "n": {"$sum": 1}}}], "cursor": {}}


def _analytics(**params):
    p = InvoiceAnalyticsParams(as_of=AS_OF, **params)
    pipeline = build_analytics_pipeline(
        criteria=build_invoice_filter(p, AS_OF), group_by=p.group_by, as_of=AS_OF, limit=p.limit
    )
    return {"aggregate": "invoices", "pipeline": pipeline, "cursor": {}}


def _coverage(direction):
    return {
        "find": "invoices", "filter": {}, "projection": {"_id": 0, "dates.postingDate": 1},
        "sort": {"dates.postingDate": direction}, "limit": 1,
    }


def _explain(database, command):
    return database.command("explain", command, verbosity="executionStats")


def _winning_stages(explain):
    stages = []

    def collect(node):
        if isinstance(node, dict):
            if "stage" in node:
                stages.append((node["stage"], node.get("indexName")))
            for value in node.values():
                collect(value)
        elif isinstance(node, list):
            for value in node:
                collect(value)

    def find_winning(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "winningPlan":
                    collect(value)
                else:
                    find_winning(value)
        elif isinstance(node, list):
            for value in node:
                find_winning(value)

    find_winning(explain)
    return stages


def _examined(explain):
    if isinstance(explain, dict):
        if "totalKeysExamined" in explain:
            return explain["totalKeysExamined"], explain["totalDocsExamined"]
        children = explain.values()
    elif isinstance(explain, list):
        children = explain
    else:
        return None
    return next(filter(None, map(_examined, children)), None)


# A page read can stop after page_size keys only if the index also delivers the sort order, so page shapes must
# show neither a SORT stage nor more keys than the page. Before these indexes every list page read all 48,839
# invoices, and the amount sort was a collection scan plus an in-memory sort.
@pytest.mark.parametrize(
    ("command", "index", "max_keys"),
    [
        (_list(), POSTING, PAGE_SIZE),
        (_list(sort_order="asc"), POSTING, PAGE_SIZE),
        (_list(status="open"), STATUS, PAGE_SIZE),
        (_list(status="cleared"), STATUS, PAGE_SIZE),
        (_list(status="overdue"), STATUS, PAGE_SIZE),
        (_list(sort_by="amount"), AMOUNT, PAGE_SIZE),
        (_list(sort_by="amount", min_amount=50_000), AMOUNT, PAGE_SIZE),
        (_list(**MARCH_2019), POSTING, PAGE_SIZE),
        (_coverage(1), POSTING, 1),
        (_coverage(-1), POSTING, 1),
        (_count(status="open"), STATUS, None),
        (_count(**MARCH_2019), POSTING, None),
        (_analytics(group_by="month", **MARCH_2019), POSTING, None),
        (_analytics(status="open", **MARCH_2019), STATUS, None),
        (_analytics(status="overdue", group_by="customer"), STATUS, None),
    ],
    ids=["list_newest_first", "list_oldest_first", "list_open", "list_cleared", "list_overdue", "list_largest_first",
         "list_min_amount_largest_first", "list_posting_range", "coverage_first", "coverage_last", "count_open",
         "count_posting_range", "analytics_posting_range_by_month", "analytics_open_in_range",
         "analytics_overdue_by_customer"],
)
def test_query_shape_is_served_by_its_compound_index(invoice_db, command, index, max_keys):
    # Arrange / Act
    explain = _explain(invoice_db, command)

    # Assert
    stages = _winning_stages(explain)
    keys, _ = _examined(explain)
    assert (
        index in {name for _, name in stages},
        [stage for stage, _ in stages if stage in INTERSECTIONS],
        max_keys is None or (keys <= max_keys and "SORT" not in {stage for stage, _ in stages}),
    ) == (True, [], True), stages


@pytest.mark.parametrize(
    "filters",
    [{"status": "open"}, {"status": "cleared"}, MARCH_2019],
    ids=["open", "cleared", "posting_range"],
)
def test_list_total_is_counted_from_index_keys_alone(invoice_db, filters):
    # Arrange / Act
    explain = _explain(invoice_db, _count(**filters))

    # Assert
    assert ("COUNT_SCAN" in {stage for stage, _ in _winning_stages(explain)}, _examined(explain)[1]) == (True, 0)


@pytest.mark.parametrize(
    "customer",
    ["cust07", "CUST07 L", "0007"],
    ids=["name_prefix", "name_prefix_any_case", "customer_number"],
)
def test_customer_filter_reads_only_the_matching_index_keys(invoice_db, customer):
    # Arrange: both $or branches must be index-bounded; the former unanchored case-insensitive name regex could
    # not be, so the whole $or fell back to reading every invoice
    criteria = build_invoice_filter(InvoiceFilter(customer=customer), AS_OF)
    matches = invoice_db["invoices"].count_documents(criteria)

    # Act
    explain = _explain(invoice_db, {"find": "invoices", "filter": criteria})

    # Assert
    keys, docs = _examined(explain)
    used = {name for _, name in _winning_stages(explain)}
    assert ({"customer.number_1", "customer.nameLower_1"} <= used, matches > 0, keys <= matches + 2, docs) == (
        True, True, True, matches
    ), (keys, docs, matches)


def test_catalog_category_budget_search_uses_category_listPrice(products):
    # Arrange: category is set on nearly every advisor search and isolates the GPUs that carry all spec fields
    criteria = build_product_filter(category="GPU", max_price=2000.0)
    pipeline = build_search_pipeline(criteria=criteria, sort_by=SortField.PRICE, order=SortOrder.ASC, page=1, page_size=10)

    # Act
    explain = _explain(products.database, {"aggregate": products.name, "pipeline": pipeline, "cursor": {}})

    # Assert
    assert "category_listPrice" in {name for _, name in _winning_stages(explain)}


@pytest.fixture
def stale_invoices(mongo_client):
    # Arrange: the index set before this layout, including the sparse clearDate index that nothing queried
    db_name = f"test_invoices_{uuid4().hex[:8]}"
    collection = mongo_client[db_name]["invoices"]
    collection.create_index([("customer.number", 1)])
    collection.create_index([("isOpen", 1), ("dates.dueInDate", 1)])
    collection.create_index([("dates.clearDate", 1)], sparse=True)

    yield collection

    # Annihilate
    mongo_client.drop_database(db_name)


def test_sync_indexes_leaves_exactly_the_declared_set(stale_invoices):
    # Act: twice, since both seed scripts run it on every load
    sync_indexes(stale_invoices, INVOICE_INDEXES)
    sync_indexes(stale_invoices, INVOICE_INDEXES)

    # Assert
    assert sorted(stale_invoices.index_information()) == sorted(["_id_", *(i.document["name"] for i in INVOICE_INDEXES)])
