from collections.abc import Mapping, Sequence
from io import BytesIO
from typing import Any

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter

from app.charts.enums import METRIC_FIELDS, METRIC_LABELS, ChartMetric, ChartType
from app.invoices.enums import GroupBy

BAR_COLOR = "#0072B2"
SEGMENTS = (("Cleared", "#009E73"), ("Open", "#0072B2"), ("Overdue", "#D55E00"))
DPI = 110
YEAR_CHARS, MONTH_CHARS = 4, 7

# Inches. A bar subplot grows with its rows; a line subplot is a fixed band.
FIGURE_WIDTH, TITLE_HEIGHT = 9.0, 0.6
LINE_HEIGHT = 3.2
BASE_HEIGHT, ROW_HEIGHT, MAX_SUBPLOT_HEIGHT = 1.4, 0.32, 9.0


def render_chart(
    *,
    currencies: Sequence[Mapping[str, Any]],
    chart_type: ChartType,
    metric: ChartMetric,
    group_by: GroupBy | None,
    title: str,
) -> bytes | None:
    field = METRIC_FIELDS[metric]
    plots = [(entry["currency"], rows) for entry in currencies if (rows := _rows(entry, field))]
    if not plots:
        return None

    # A line runs left to right; bars are horizontal, so their value axis is x and
    # they grow taller with every row.
    vertical = chart_type is ChartType.LINE
    tallest = max(len(rows) for _, rows in plots)
    subplot_height = LINE_HEIGHT if vertical else min(BASE_HEIGHT + ROW_HEIGHT * tallest, MAX_SUBPLOT_HEIGHT)
    figure = Figure(figsize=(FIGURE_WIDTH, subplot_height * len(plots) + TITLE_HEIGHT), dpi=DPI)

    for axis, (currency, rows) in zip(figure.subplots(len(plots), 1, squeeze=False).flat, plots, strict=True):
        if chart_type is ChartType.LINE:
            _draw_line(axis, rows, field, group_by)
        elif chart_type is ChartType.BAR:
            _draw_bar(axis, rows, field)
        else:
            _draw_stacked(axis, rows)
        axis.set_title(currency, loc="left", fontsize=10, fontweight="bold")
        axis.grid(axis="y" if vertical else "x", linestyle=":", alpha=0.6)
        # A FuncFormatter binds to its axis, so each one needs its own.
        value_axis = axis.yaxis if vertical else axis.xaxis
        value_axis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:,.0f}"))
        value_axis.set_label_text(METRIC_LABELS[metric], fontsize=9)

    figure.suptitle(title, fontsize=12, fontweight="bold", x=0.02, ha="left")
    figure.tight_layout(rect=(0, 0, 1, 0.97))

    buffer = BytesIO()
    FigureCanvasAgg(figure).print_png(buffer)
    return buffer.getvalue()


def _rows(entry: Mapping[str, Any], field: str) -> list[Mapping[str, Any]]:
    return [row for row in entry["rows"] if row.get(field) is not None]


def _categories(axis: Any, rows: Sequence[Mapping[str, Any]]) -> range:
    positions = range(len(rows))
    axis.set_yticks(positions)
    axis.set_yticklabels([str(row.get("label") or row.get("key") or "Total") for row in rows], fontsize=8)
    axis.invert_yaxis()
    return positions


def _draw_line(axis: Any, rows: Sequence[Mapping[str, Any]], field: str, group_by: GroupBy | None) -> None:
    # Period keys are "YYYY-MM-DD"; a year reads better as "2019" than "2019-01".
    kept = YEAR_CHARS if group_by is GroupBy.YEAR else MONTH_CHARS
    axis.plot(range(len(rows)), [row[field] for row in rows], marker="o", linewidth=2, color=BAR_COLOR)
    axis.set_ylim(bottom=0)
    axis.set_xticks(range(len(rows)))
    axis.set_xticklabels([row["key"][:kept] for row in rows], rotation=45, ha="right", fontsize=8)


def _draw_bar(axis: Any, rows: Sequence[Mapping[str, Any]], field: str) -> None:
    axis.barh(_categories(axis, rows), [row[field] for row in rows], color=BAR_COLOR, height=0.7)


def _draw_stacked(axis: Any, rows: Sequence[Mapping[str, Any]]) -> None:
    positions = _categories(axis, rows)
    split = [_segments(row) for row in rows]
    offsets = [0.0] * len(rows)
    for widths, (name, color) in zip(zip(*split, strict=True), SEGMENTS, strict=True):
        axis.barh(positions, widths, left=offsets, color=color, height=0.7, label=name)
        offsets = [offset + width for offset, width in zip(offsets, widths, strict=True)]
    axis.legend(fontsize=8, loc="lower right", bbox_to_anchor=(1, 1), ncols=len(SEGMENTS), frameon=False)


def _segments(row: Mapping[str, Any]) -> tuple[float, float, float]:
    total, opened = row["totalAmount"] or 0.0, row.get("openAmount") or 0.0
    overdue = row.get("overdueAmount") or 0.0
    return round(max(total - opened, 0.0), 2), round(max(opened - overdue, 0.0), 2), round(max(overdue, 0.0), 2)
