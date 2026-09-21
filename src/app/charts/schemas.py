from typing import Self

from pydantic import model_validator

from app.charts.enums import LINE_GRAIN_METRICS, ChartMetric, ChartType
from app.invoices.enums import LINE_ITEM_FIELDS, PERIOD_UNITS, GroupBy
from app.invoices.schemas import InvoiceAnalyticsParams


class ChartParams(InvoiceAnalyticsParams):
    chart_type: ChartType
    metric: ChartMetric = ChartMetric.TOTAL

    @model_validator(mode="after")
    def _reject_unplottable_combinations(self) -> Self:
        if self.metric in LINE_GRAIN_METRICS and self.group_by not in LINE_ITEM_FIELDS:
            allowed = ", ".join(sorted(LINE_ITEM_FIELDS))
            raise ValueError(f"metric ({self.metric}) needs group_by to be one of: {allowed}")
        if self.metric is ChartMetric.AVERAGE_UNIT_PRICE and self.group_by is not GroupBy.PRODUCT:
            raise ValueError(f"metric ({self.metric}) needs group_by to be {GroupBy.PRODUCT}")
        if self.chart_type is ChartType.LINE and self.group_by not in PERIOD_UNITS:
            allowed = ", ".join(sorted(PERIOD_UNITS))
            raise ValueError(f"chart_type (line) needs group_by to be one of: {allowed}")
        if self.chart_type is ChartType.STACKED and self.metric is not ChartMetric.TOTAL:
            raise ValueError("chart_type (stacked) splits the total, so metric must be total")
        if self.chart_type is ChartType.BAR and self.group_by is None:
            raise ValueError("chart_type (bar) needs a group_by; a single row is not a chart")
        return self
