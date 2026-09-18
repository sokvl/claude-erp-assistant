from collections.abc import Mapping
from enum import StrEnum


class InvoiceStatus(StrEnum):
    OPEN = "open"
    CLEARED = "cleared"
    OVERDUE = "overdue"


class InvoiceSortField(StrEnum):
    POSTING_DATE = "posting_date"
    AMOUNT = "amount"


class GroupBy(StrEnum):
    CUSTOMER = "customer"
    PRODUCT = "product"
    BRAND = "brand"
    CATEGORY = "category"
    MONTH = "month"
    QUARTER = "quarter"
    YEAR = "year"


SORT_PATHS: Mapping[InvoiceSortField, str] = {
    InvoiceSortField.POSTING_DATE: "dates.postingDate",
    InvoiceSortField.AMOUNT: "amounts.totalOpen",
}

LINE_ITEM_FIELDS: Mapping[GroupBy, str] = {
    GroupBy.PRODUCT: "sku",
    GroupBy.BRAND: "brand",
    GroupBy.CATEGORY: "category",
}

PERIOD_UNITS: Mapping[GroupBy, str] = {
    GroupBy.MONTH: "month",
    GroupBy.QUARTER: "quarter",
    GroupBy.YEAR: "year",
}
