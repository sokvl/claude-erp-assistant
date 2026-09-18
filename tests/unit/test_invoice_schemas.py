import re
from datetime import date

import pytest
from pydantic import ValidationError

from app.catalog.enums import SortOrder
from app.invoices.enums import InvoiceSortField
from app.invoices.schemas import InvoiceAnalyticsParams, InvoiceFilter, InvoiceListParams
from app.limits import MAX_AMOUNT, MAX_ANALYTICS_ROWS, MAX_PAGE, MAX_PAGE_SIZE, MAX_TEXT_LENGTH


def test_invoice_list_params_defaults_are_newest_first_page():
    # Arrange / Act
    params = InvoiceListParams()

    # Assert
    assert (params.sort_by, params.sort_order, params.page, params.page_size, params.as_of) == (
        InvoiceSortField.POSTING_DATE,
        SortOrder.DESC,
        1,
        20,
        None,
    )


def test_invoice_analytics_params_defaults_leave_grouping_and_row_count_open():
    # Arrange / Act
    params = InvoiceAnalyticsParams()

    # Assert
    assert (params.group_by, params.limit) == (None, None)


@pytest.mark.parametrize(
    ("model", "kwargs"),
    [
        (InvoiceFilter, {"posted_from": "2020-01-01", "posted_to": "2020-01-01"}),
        (InvoiceFilter, {"min_amount": 0, "max_amount": 0}),
        (InvoiceFilter, {"min_amount": MAX_AMOUNT}),
        (InvoiceFilter, {"customer": "x" * MAX_TEXT_LENGTH}),
        (InvoiceFilter, {"currency": "CAD", "status": "overdue", "as_of": "2020-05-31"}),
        (InvoiceListParams, {"page": MAX_PAGE, "page_size": MAX_PAGE_SIZE, "sort_by": "amount", "sort_order": "asc"}),
        (InvoiceAnalyticsParams, {"group_by": "quarter", "limit": MAX_ANALYTICS_ROWS}),
    ],
    ids=["single_day", "zero_amounts", "max_amount", "max_customer_length", "status_with_as_of",
         "list_bounds", "analytics_bounds"],
)
def test_invoice_params_boundary_values_are_accepted(model, kwargs):
    # Arrange / Act
    params = model(**kwargs)

    # Assert
    assert params.model_dump(exclude_defaults=True).keys() == kwargs.keys()


@pytest.mark.parametrize(
    ("model", "kwargs", "message"),
    [
        (InvoiceFilter, {"posted_from": "2020-02-01", "posted_to": "2020-01-01"},
         "posted_from (2020-02-01) must not exceed posted_to (2020-01-01)"),
        (InvoiceFilter, {"min_amount": 500, "max_amount": 100}, "min_amount (500.0) must not exceed max_amount (100.0)"),
        (InvoiceFilter, {"posted_from": "2020-02-30"}, "posted_from"),
        (InvoiceFilter, {"posted_from": "last quarter"}, "posted_from"),
        (InvoiceFilter, {"currency": "usd"}, "currency"),
        (InvoiceFilter, {"currency": "US$"}, "currency"),
        (InvoiceFilter, {"status": "late"}, "status"),
        (InvoiceFilter, {"min_amount": -1}, "min_amount"),
        (InvoiceFilter, {"max_amount": MAX_AMOUNT + 1}, "max_amount"),
        (InvoiceFilter, {"min_amount": float("nan")}, "min_amount"),
        (InvoiceFilter, {"customer": "x" * (MAX_TEXT_LENGTH + 1)}, "customer"),
        (InvoiceFilter, {"region": "EU"}, "region"),
        (InvoiceListParams, {"page": 0}, "page"),
        (InvoiceListParams, {"page_size": MAX_PAGE_SIZE + 1}, "page_size"),
        (InvoiceListParams, {"sort_by": "customer"}, "sort_by"),
        (InvoiceAnalyticsParams, {"group_by": "week"}, "group_by"),
        (InvoiceAnalyticsParams, {"limit": 0}, "limit"),
        (InvoiceAnalyticsParams, {"limit": MAX_ANALYTICS_ROWS + 1}, "limit"),
    ],
    ids=["inverted_dates", "inverted_amounts", "impossible_date", "relative_date_text", "lowercase_currency",
         "currency_symbol", "unknown_status", "negative_amount", "amount_over_cap", "nan_amount",
         "customer_too_long", "unknown_field", "page_zero", "page_size_over_cap", "unknown_sort_field",
         "unknown_group_by", "zero_limit", "limit_over_cap"],
)
def test_invoice_params_invalid_values_raise_validation_error(model, kwargs, message):
    # Arrange / Act / Assert
    with pytest.raises(ValidationError, match=re.escape(message)):
        model(**kwargs)


def test_invoice_filter_parses_iso_date_strings_into_dates():
    # Arrange / Act
    params = InvoiceFilter(posted_from="2020-01-01", as_of="2020-05-31")

    # Assert
    assert (params.posted_from, params.as_of) == (date(2020, 1, 1), date(2020, 5, 31))
