from datetime import datetime

import pytest

from app.charts.schemas import ChartParams
from app.charts.service import chart_analytics

ROWS = [
    {
        "currency": "USD",
        "groupCount": 2,
        "rows": [
            {"key": "2019-01-01", "invoiceCount": 3, "totalAmount": 900.0, "averageAmount": 300.0,
             "openAmount": 400.0, "overdueAmount": 100.0, "averageDaysToPay": 12.0},
            {"key": "2019-02-01", "invoiceCount": 1, "totalAmount": 300.0, "averageAmount": 300.0,
             "openAmount": 0.0, "overdueAmount": 0.0, "averageDaysToPay": 9.0},
        ],
    }
]


class FakeInvoices:
    def __init__(self, currencies):
        self.currencies = currencies

    def aggregate(self, pipeline, **kwargs):
        return iter(self.currencies)

    def find_one(self, *args, **kwargs):
        return {"dates": {"postingDate": datetime(2019, 1, 2)}}


class FakeCharts:
    def __init__(self):
        self.documents = []

    def insert_one(self, document):
        self.documents.append(document)


def _params(**overrides):
    return ChartParams.model_validate({"chart_type": "line", "group_by": "month"} | overrides)


# The chart is rendered from what the aggregation returned, and the rows travel back
# unchanged so the answer quotes database figures rather than anything read off a picture.
def test_chartAnalytics_matchingInvoices_returnsTheRowsAndAStoredChart():
    # Arrange
    charts = FakeCharts()

    # Act
    result = chart_analytics(FakeInvoices(ROWS), charts, _params(), "conv-1")

    # Assert
    [stored] = charts.documents
    assert result["chartId"] == stored["_id"]
    assert result["currencies"] == ROWS
    assert result["coverage"] == {"firstPostingDate": "2019-01-02", "lastPostingDate": "2019-01-02"}
    assert bytes(stored["image"]).startswith(b"\x89PNG")


# analyze_invoices echoes back the filters it applied and the analyst states them,
# so the drawing options must not travel with them and be read out as filters.
def test_chartAnalytics_always_echoesOnlyTheInvoiceFilters():
    # Arrange
    params = _params(posted_from="2019-01-01", posted_to="2019-12-31", currency="USD", metric="open")

    # Act
    result = chart_analytics(FakeInvoices(ROWS), FakeCharts(), params, "conv-1")

    # Assert
    assert result["filters"] == {"posted_from": "2019-01-01", "posted_to": "2019-12-31", "currency": "USD"}


def test_chartAnalytics_noMatchingInvoices_returnsNoChartIdAndStoresNothing():
    # Arrange
    charts = FakeCharts()

    # Act
    result = chart_analytics(FakeInvoices([]), charts, _params(), "conv-1")

    # Assert
    assert (result["chartId"], charts.documents) == (None, [])
    assert result["currencies"] == []


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({}, "Invoiced by month"),
        ({"metric": "overdue"}, "Overdue by month"),
        ({"chart_type": "stacked", "group_by": "customer"}, "Cleared, open and overdue by customer"),
        ({"chart_type": "stacked", "group_by": None}, "Cleared, open and overdue"),
        ({"posted_from": "2019-01-01", "posted_to": "2019-03-31"},
         "Invoiced by month, 2019-01-01 to 2019-03-31"),
        ({"posted_from": "2019-01-01"}, "Invoiced by month, 2019-01-01"),
    ],
    ids=["default", "other_metric", "stacked_grouped", "stacked_totals", "both_dates", "open_ended"],
)
def test_chartAnalytics_params_titleNamesTheMetricGroupingAndPeriod(overrides, expected):
    # Arrange / Act
    result = chart_analytics(FakeInvoices(ROWS), FakeCharts(), _params(**overrides), "conv-1")

    # Assert
    assert result["chartTitle"] == expected
