from collections.abc import Mapping
from enum import StrEnum


class ChartType(StrEnum):
    LINE = "line"
    BAR = "bar"
    STACKED = "stacked"


class ChartMetric(StrEnum):
    TOTAL = "total"
    OPEN = "open"
    OVERDUE = "overdue"
    AVERAGE = "average"
    COUNT = "count"
    UNITS = "units"
    AVERAGE_UNIT_PRICE = "average_unit_price"
    AVERAGE_DAYS_TO_PAY = "average_days_to_pay"


METRIC_FIELDS: Mapping[ChartMetric, str] = {
    ChartMetric.TOTAL: "totalAmount",
    ChartMetric.OPEN: "openAmount",
    ChartMetric.OVERDUE: "overdueAmount",
    ChartMetric.AVERAGE: "averageAmount",
    ChartMetric.COUNT: "invoiceCount",
    ChartMetric.UNITS: "units",
    ChartMetric.AVERAGE_UNIT_PRICE: "averageUnitPrice",
    ChartMetric.AVERAGE_DAYS_TO_PAY: "averageDaysToPay",
}

METRIC_LABELS: Mapping[ChartMetric, str] = {
    ChartMetric.TOTAL: "Invoiced",
    ChartMetric.OPEN: "Open",
    ChartMetric.OVERDUE: "Overdue",
    ChartMetric.AVERAGE: "Average per invoice",
    ChartMetric.COUNT: "Invoices",
    ChartMetric.UNITS: "Units",
    ChartMetric.AVERAGE_UNIT_PRICE: "Average unit price",
    ChartMetric.AVERAGE_DAYS_TO_PAY: "Average days to pay",
}

LINE_GRAIN_METRICS = frozenset({ChartMetric.UNITS, ChartMetric.AVERAGE_UNIT_PRICE})
