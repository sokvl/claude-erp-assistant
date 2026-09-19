import copy
from datetime import date, datetime

import bson
import pytest

from app.catalog.enums import SortOrder
from app.invoices.enums import GroupBy, InvoiceSortField
from app.invoices.query import (
    INVOICE_PROJECTION,
    build_analytics_pipeline,
    build_invoice_filter,
    build_list_query,
)
from app.invoices.schemas import InvoiceFilter
from app.limits import DEFAULT_ANALYTICS_ROWS, MAX_ANALYTICS_ROWS

AS_OF = date(2020, 5, 31)
END_OF_DAY = (23, 59, 59, 999999)


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({}, {}),
        # a date range covers both whole days
        (
            {"posted_from": date(2020, 1, 1), "posted_to": date(2020, 3, 31)},
            {"dates.postingDate": {"$gte": datetime(2020, 1, 1), "$lte": datetime(2020, 3, 31, *END_OF_DAY)}},
        ),
        ({"posted_from": date(2020, 1, 1)}, {"dates.postingDate": {"$gte": datetime(2020, 1, 1)}}),
        ({"posted_to": date(2020, 1, 1)}, {"dates.postingDate": {"$lte": datetime(2020, 1, 1, *END_OF_DAY)}}),
        # the last representable day has no "next day" to compare against
        ({"posted_to": date.max}, {"dates.postingDate": {"$lte": datetime(9999, 12, 31, *END_OF_DAY)}}),
        (
            {"customer": "0200769623"},
            {"$or": [
                {"customer.number": "0200769623"},
                {"customer.nameLower": {"$regex": "^0200769623"}},
            ]},
        ),
        # any case matches without $options "i": a case-insensitive or unanchored regex cannot be bounded
        # by the nameLower index and scans every key, a left-anchored lowercase prefix reads only its matches
        (
            {"customer": "Wal-Mar"},
            {"$or": [
                {"customer.number": "Wal-Mar"},
                {"customer.nameLower": {"$regex": r"^wal\-mar"}},
            ]},
        ),
        # user text is matched literally, never as a regular expression
        (
            {"customer": "A.B*("},
            {"$or": [
                {"customer.number": "A.B*("},
                {"customer.nameLower": {"$regex": r"^a\.b\*\("}},
            ]},
        ),
        ({"customer": ""}, {}),
        ({"currency": "CAD"}, {"currency": "CAD"}),
        ({"status": "open"}, {"isOpen": True}),
        ({"status": "cleared"}, {"isOpen": False}),
        # due exactly on the as-of date is not overdue yet
        ({"status": "overdue"}, {"isOpen": True, "dates.dueInDate": {"$lt": datetime(2020, 5, 31)}}),
        # zero is a real bound - a truthiness check would drop it
        ({"min_amount": 0}, {"amounts.totalOpen": {"$gte": 0}}),
        ({"min_amount": 100, "max_amount": 500}, {"amounts.totalOpen": {"$gte": 100, "$lte": 500}}),
        (
            {"posted_from": date(2019, 1, 1), "customer": "WAL-MAR", "currency": "USD", "status": "overdue",
             "max_amount": 1000},
            {
                "dates.postingDate": {"$gte": datetime(2019, 1, 1)},
                "$or": [
                    {"customer.number": "WAL-MAR"},
                    {"customer.nameLower": {"$regex": r"^wal\-mar"}},
                ],
                "currency": "USD",
                "isOpen": True,
                "dates.dueInDate": {"$lt": datetime(2020, 5, 31)},
                "amounts.totalOpen": {"$lte": 1000},
            },
        ),
    ],
    ids=["no_filters", "date_range_inclusive", "from_only", "to_only", "to_last_day", "customer_number_or_name",
         "customer_name_prefix_lowercased", "customer_regex_escaped", "customer_empty", "currency", "open", "cleared", "overdue_before_as_of",
         "min_amount_zero", "amount_range", "all_filters"],
)
def test_build_invoice_filter_builds_expected_criteria(kwargs, expected):
    # Arrange
    filters = InvoiceFilter(**kwargs)

    # Act
    criteria = build_invoice_filter(filters, AS_OF)

    # Assert
    assert criteria == expected


def test_build_invoice_filter_dates_are_bson_encodable_datetimes():
    # Arrange: pymongo rejects datetime.date, which would surface as a 500 instead of a 503 or 422
    filters = InvoiceFilter(posted_from=date(2020, 1, 1), posted_to=date(2020, 1, 31), status="overdue")

    # Act
    decoded = bson.decode(bson.encode(build_invoice_filter(filters, AS_OF)))

    # Assert
    assert (decoded["dates.postingDate"]["$gte"], decoded["dates.dueInDate"]["$lt"]) == (
        datetime(2020, 1, 1),
        datetime(2020, 5, 31),
    )


def _list_query(**overrides):
    kwargs = {
        "criteria": {"isOpen": True},
        "sort_by": InvoiceSortField.POSTING_DATE,
        "order": SortOrder.DESC,
        "page": 1,
        "page_size": 20,
    }
    kwargs.update(overrides)
    return build_list_query(**kwargs)


@pytest.mark.parametrize(
    ("sort_by", "order", "expected"),
    [
        (InvoiceSortField.POSTING_DATE, SortOrder.DESC, [("dates.postingDate", -1), ("_id", -1)]),
        (InvoiceSortField.AMOUNT, SortOrder.ASC, [("amounts.totalOpen", 1), ("_id", 1)]),
    ],
    ids=["newest_first", "smallest_first"],
)
def test_build_list_query_sorts_with_id_tiebreak(sort_by, order, expected):
    # Arrange / Act
    query = _list_query(sort_by=sort_by, order=order)

    # Assert
    assert query["sort"] == expected


# A find with skip/limit stops reading after the page, and the count of an indexed filter reads only index keys.
# The former $facet pushed every matching document through the pipeline just to count it (48,839 reads per page).
@pytest.mark.parametrize(
    ("page", "page_size", "expected_skip"),
    [(1, 20, 0), (3, 10, 20)],
    ids=["first_page", "third_page"],
)
def test_build_list_query_is_a_bounded_find_over_the_criteria(page, page_size, expected_skip):
    # Arrange / Act
    query = _list_query(page=page, page_size=page_size)

    # Assert
    assert query == {
        "filter": {"isOpen": True},
        "projection": INVOICE_PROJECTION,
        "sort": [("dates.postingDate", -1), ("_id", -1)],
        "skip": expected_skip,
        "limit": page_size,
    }


def test_invoice_projection_hides_the_customer_search_key():
    # Arrange / Act: customer.nameLower exists only to make the name prefix search index-bounded
    customer_fields = sorted(field for field in INVOICE_PROJECTION if field.startswith("customer"))

    # Assert
    assert customer_fields == ["customer.name", "customer.number"]


@pytest.mark.parametrize(
    ("overrides", "message"),
    [({"sort_by": "posting_date"}, "sort_by"), ({"order": "desc"}, "order")],
    ids=["raw_sort_by", "raw_order"],
)
def test_build_list_query_raw_string_raises_value_error(overrides, message):
    # Arrange / Act / Assert
    with pytest.raises(ValueError, match=message):
        _list_query(**overrides)


def _analytics(group_by=None, limit=None, criteria=None):
    return build_analytics_pipeline(
        criteria={} if criteria is None else criteria, group_by=group_by, as_of=AS_OF, limit=limit
    )


def _stages(pipeline):
    return [next(iter(stage)) for stage in pipeline]


def _row_selection(pipeline):
    return pipeline[-3]["$group"]["rows"]["$topN"]


@pytest.mark.parametrize(
    ("group_by", "expected"),
    [
        (None, ["$match", "$project", "$group", "$set", "$group", "$sort", "$project"]),
        (GroupBy.CUSTOMER, ["$match", "$project", "$group", "$set", "$group", "$sort", "$project"]),
        (GroupBy.QUARTER, ["$match", "$project", "$group", "$set", "$group", "$sort", "$project"]),
        (GroupBy.CATEGORY, ["$match", "$unwind", "$group", "$set", "$group", "$set", "$group", "$sort", "$project"]),
    ],
    ids=["totals", "customer", "quarter", "category"],
)
def test_build_analytics_pipeline_stage_order_per_grain(group_by, expected):
    # Arrange / Act
    pipeline = _analytics(group_by)

    # Assert
    assert _stages(pipeline) == expected


@pytest.mark.parametrize(
    ("group_by", "field"),
    [(GroupBy.PRODUCT, "sku"), (GroupBy.BRAND, "brand"), (GroupBy.CATEGORY, "category")],
    ids=["product", "brand", "category"],
)
def test_build_analytics_pipeline_line_grain_unwinds_embedded_lines_per_invoice(group_by, field):
    # Arrange: lines are embedded in their invoice; a $lookup into a line collection cost ~1.4 s for all invoices.
    # Grouping by (key, invoice) first makes an invoice with two GPU lines count as one GPU invoice.
    pipeline = _analytics(group_by)

    # Act
    unwind, per_invoice = pipeline[1], pipeline[2]["$group"]["_id"]

    # Assert
    assert (unwind, per_invoice) == ({"$unwind": "$lines"}, {"key": f"$lines.{field}", "invoice": "$_id"})


def test_build_analytics_pipeline_ranks_rows_within_each_currency():
    # Arrange: a CAD total must never be ranked against a USD total
    pipeline = _analytics(GroupBy.CUSTOMER)

    # Act
    per_currency = pipeline[-3]["$group"]

    # Assert
    assert (pipeline[2]["$group"]["_id"], per_currency["_id"], _row_selection(pipeline)["sortBy"]) == (
        {"key": "$key", "currency": "$currency"},
        "$_id.currency",
        {"totalAmount": -1, "_id.key": 1},
    )


@pytest.mark.parametrize(
    ("group_by", "limit", "expected_rows", "expected_sort"),
    [
        (GroupBy.CUSTOMER, None, DEFAULT_ANALYTICS_ROWS, {"totalAmount": -1, "_id.key": 1}),
        (GroupBy.CUSTOMER, 5, 5, {"totalAmount": -1, "_id.key": 1}),
        # a default of ten would cut a monthly trend of one year to its first ten months
        (GroupBy.MONTH, None, MAX_ANALYTICS_ROWS, {"_id.key": 1}),
        (GroupBy.MONTH, 3, 3, {"_id.key": 1}),
    ],
    ids=["ranking_default", "ranking_limit", "period_default_keeps_whole_trend", "period_limit"],
)
def test_build_analytics_pipeline_row_count_and_order_depend_on_grouping(group_by, limit, expected_rows, expected_sort):
    # Arrange / Act
    selection = _row_selection(_analytics(group_by, limit))

    # Assert
    assert (selection["n"], selection["sortBy"]) == (expected_rows, expected_sort)


@pytest.mark.parametrize(
    ("group_by", "expected"),
    [
        (None, ["invoiceCount", "totalAmount", "averageAmount", "openAmount", "overdueAmount", "averageDaysToPay"]),
        (GroupBy.CUSTOMER, ["key", "label", "invoiceCount", "totalAmount", "averageAmount", "openAmount",
                            "overdueAmount", "averageDaysToPay"]),
        (GroupBy.YEAR, ["key", "invoiceCount", "totalAmount", "averageAmount", "openAmount", "overdueAmount",
                        "averageDaysToPay"]),
        (GroupBy.BRAND, ["key", "invoiceCount", "totalAmount", "averageAmount", "openAmount", "overdueAmount",
                         "averageDaysToPay", "units"]),
        (GroupBy.PRODUCT, ["key", "label", "invoiceCount", "totalAmount", "averageAmount", "openAmount",
                           "overdueAmount", "averageDaysToPay", "units", "averageUnitPrice"]),
    ],
    ids=["totals", "customer", "year", "brand", "product"],
)
def test_build_analytics_pipeline_row_fields_per_grouping(group_by, expected):
    # Arrange / Act
    output = _row_selection(_analytics(group_by))["output"]

    # Assert
    assert list(output) == expected


def test_build_analytics_pipeline_overdue_uses_as_of_midnight():
    # Arrange / Act
    kpis = _analytics()[2]["$group"]

    # Assert
    assert kpis["overdueAmount"] == {
        "$sum": {"$cond": [{"$and": ["$isOpen", {"$lt": ["$dueInDate", datetime(2020, 5, 31)]}]}, "$amount", 0]}
    }


@pytest.mark.parametrize(
    ("group_by", "unit"),
    [(GroupBy.MONTH, "month"), (GroupBy.QUARTER, "quarter"), (GroupBy.YEAR, "year")],
    ids=["month", "quarter", "year"],
)
def test_build_analytics_pipeline_period_key_is_first_day_of_period(group_by, unit):
    # Arrange / Act
    key = _analytics(group_by)[1]["$project"]["key"]

    # Assert
    assert key == {
        "$dateToString": {"format": "%Y-%m-%d", "date": {"$dateTrunc": {"date": "$dates.postingDate", "unit": unit}}}
    }


def test_build_analytics_pipeline_rounds_money_after_grouping():
    # Arrange / Act
    rounded = _analytics(GroupBy.PRODUCT)[5]["$set"]

    # Assert
    assert (rounded["totalAmount"], rounded["averageDaysToPay"], rounded["averageUnitPrice"]) == (
        {"$round": ["$totalAmount", 2]},
        {"$round": ["$averageDaysToPay", 1]},
        {"$round": [{"$divide": ["$totalAmount", "$units"]}, 2]},
    )


def test_build_analytics_pipeline_raw_string_group_by_raises_value_error():
    # Arrange / Act / Assert
    with pytest.raises(ValueError, match="group_by"):
        _analytics("customer")


def test_build_analytics_pipeline_does_not_mutate_criteria():
    # Arrange
    criteria = {"currency": "USD"}
    snapshot = copy.deepcopy(criteria)

    # Act
    _analytics(GroupBy.CATEGORY, criteria=criteria)

    # Assert
    assert criteria == snapshot
