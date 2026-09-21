from datetime import date

import pytest

from app.charts.enums import METRIC_FIELDS, METRIC_LABELS, ChartMetric
from app.invoices.enums import GroupBy
from app.invoices.query import build_analytics_pipeline


def _row_fields(group_by):
    pipeline = build_analytics_pipeline(criteria={}, group_by=group_by, as_of=date(2020, 1, 1), limit=None)
    [rollup] = [stage["$group"] for stage in pipeline if "$group" in stage and "rows" in stage.get("$group", {})]
    return set(rollup["rows"]["$topN"]["output"])


@pytest.mark.parametrize("metric", list(ChartMetric), ids=[metric.value for metric in ChartMetric])
def test_chartMetric_everyMember_hasAFieldAndALabel(metric):
    # Arrange / Act / Assert
    assert metric in METRIC_FIELDS and metric in METRIC_LABELS


# METRIC_FIELDS points at keys analyze_invoices puts in its rows. A name that drifts
# apart would not raise: render drops rows whose field is missing, so the chart would
# quietly come back empty. Product rows are the richest, carrying every metric.
@pytest.mark.parametrize("metric", list(ChartMetric), ids=[metric.value for metric in ChartMetric])
def test_metricFields_everyMetric_namesAKeyTheAnalyticsRowsCarry(metric):
    # Arrange / Act
    produced = _row_fields(GroupBy.PRODUCT)

    # Assert
    assert METRIC_FIELDS[metric] in produced


# Only product rows carry averageUnitPrice and only line-grain rows carry units,
# which is what ChartParams enforces; the rest must exist on every grouping.
@pytest.mark.parametrize(
    "group_by",
    [None, *GroupBy],
    ids=["no_grouping", *[member.value for member in GroupBy]],
)
def test_metricFields_everyGrouping_carriesTheMetricsItsChartsAllow(group_by):
    # Arrange
    line_grain_only = {ChartMetric.UNITS, ChartMetric.AVERAGE_UNIT_PRICE}
    always = [metric for metric in ChartMetric if metric not in line_grain_only]

    # Act
    produced = _row_fields(group_by)

    # Assert
    assert {METRIC_FIELDS[metric] for metric in always} <= produced
