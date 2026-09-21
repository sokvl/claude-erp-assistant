import pytest
from pydantic import ValidationError

from app.charts.enums import ChartMetric, ChartType
from app.charts.schemas import ChartParams


@pytest.mark.parametrize(
    "params",
    [
        {"chart_type": "line", "group_by": "month"},
        {"chart_type": "line", "group_by": "year", "metric": "count"},
        {"chart_type": "bar", "group_by": "customer"},
        {"chart_type": "bar", "group_by": "product", "metric": "average_unit_price"},
        {"chart_type": "bar", "group_by": "brand", "metric": "units"},
        {"chart_type": "stacked", "group_by": "customer"},
        {"chart_type": "stacked"},
    ],
    ids=["line_month", "line_year_count", "bar_customer", "bar_product_unit_price",
         "bar_brand_units", "stacked_customer", "stacked_totals"],
)
def test_chartParams_plottableCombination_isAccepted(params):
    # Arrange / Act
    result = ChartParams.model_validate(params)

    # Assert
    assert (result.chart_type, result.group_by) == (params["chart_type"], params.get("group_by"))


# Every rule below rejects a chart the analytics rows cannot produce, so the model
# gets a correctable is_error instead of an empty or misleading picture.
@pytest.mark.parametrize(
    ("params", "expected_message"),
    [
        ({"chart_type": "bar", "group_by": "customer", "metric": "units"}, "needs group_by to be one of"),
        ({"chart_type": "line", "group_by": "month", "metric": "units"}, "needs group_by to be one of"),
        ({"chart_type": "bar", "group_by": "brand", "metric": "average_unit_price"}, "needs group_by to be product"),
        ({"chart_type": "line", "group_by": "customer"}, "line) needs group_by to be one of"),
        ({"chart_type": "line"}, "line) needs group_by to be one of"),
        ({"chart_type": "stacked", "group_by": "month", "metric": "open"}, "metric must be total"),
        ({"chart_type": "bar"}, "bar) needs a group_by"),
    ],
    ids=["units_without_line_grain", "units_on_period", "unit_price_not_product",
         "line_over_customers", "line_without_grouping", "stacked_other_metric", "bar_without_grouping"],
)
def test_chartParams_unplottableCombination_isRejected(params, expected_message):
    # Arrange / Act
    with pytest.raises(ValidationError) as raised:
        ChartParams.model_validate(params)

    # Assert
    assert expected_message in str(raised.value)


@pytest.mark.parametrize("chart_type", list(ChartType), ids=[member.value for member in ChartType])
def test_chartParams_everyChartType_isReachable(chart_type):
    # Arrange
    group_by = {ChartType.LINE: "month", ChartType.BAR: "customer", ChartType.STACKED: None}[chart_type]

    # Act
    result = ChartParams.model_validate({"chart_type": chart_type, "group_by": group_by})

    # Assert
    assert result.chart_type is chart_type


@pytest.mark.parametrize("metric", list(ChartMetric), ids=[member.value for member in ChartMetric])
def test_chartParams_everyMetric_isReachable(metric):
    # Arrange: product is the one grouping whose rows carry every metric
    # Act
    result = ChartParams.model_validate({"chart_type": "bar", "group_by": "product", "metric": metric})

    # Assert
    assert result.metric is metric


def test_chartParams_defaults_metricToTotal():
    # Arrange / Act
    result = ChartParams.model_validate({"chart_type": "bar", "group_by": "customer"})

    # Assert
    assert result.metric is ChartMetric.TOTAL


def test_chartParams_inheritsInvoiceFilterValidation():
    # Arrange / Act
    with pytest.raises(ValidationError) as raised:
        ChartParams.model_validate(
            {"chart_type": "bar", "group_by": "customer", "posted_from": "2020-02-01", "posted_to": "2020-01-01"}
        )

    # Assert
    assert "posted_from (2020-02-01) must not exceed posted_to (2020-01-01)" in str(raised.value)


def test_chartParams_unknownField_isRejected():
    # Arrange / Act
    with pytest.raises(ValidationError) as raised:
        ChartParams.model_validate({"chart_type": ChartType.BAR, "group_by": "customer", "palette": "neon"})

    # Assert
    assert "Extra inputs are not permitted" in str(raised.value)
