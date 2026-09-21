from typing import Any

from app.charts.enums import METRIC_LABELS, ChartType
from app.charts.render import render_chart
from app.charts.schemas import ChartParams
from app.charts.storage import save_chart
from app.invoices.schemas import InvoiceAnalyticsParams
from app.invoices.service import analyze_invoices

DRAWING_FIELDS = {"chart_type", "metric"}


def chart_analytics(
    invoices: Any,
    charts: Any,
    params: ChartParams,
    conversation_id: str | None = None,
) -> dict[str, Any]:
    figures = InvoiceAnalyticsParams.model_validate(params.model_dump(exclude=DRAWING_FIELDS))
    result = analyze_invoices(invoices, figures)
    title = _title(params)
    image = render_chart(
        currencies=result["currencies"],
        chart_type=params.chart_type,
        metric=params.metric,
        group_by=params.group_by,
        title=title,
    )
    chart_id = None if image is None else save_chart(charts, conversation_id, params, title, image)
    return {"chartId": chart_id, "chartTitle": title, **result}


def _title(params: ChartParams) -> str:
    base = "Cleared, open and overdue" if params.chart_type is ChartType.STACKED else METRIC_LABELS[params.metric]
    if params.group_by:
        base = f"{base} by {params.group_by}"
    period = " to ".join(str(day) for day in (params.posted_from, params.posted_to) if day)
    return f"{base}, {period}" if period else base
