import pytest

from app.charts import render as render_module
from app.charts.enums import ChartMetric, ChartType
from app.charts.render import _segments, render_chart
from app.invoices.enums import GroupBy
from app.limits import MAX_CHART_BYTES

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _drawn_axes(monkeypatch, **kwargs):
    """Render, and hand back the axes that were actually drawn on."""
    axes = []

    class SpyFigure(render_module.Figure):
        def subplots(self, *args, **subplot_kwargs):
            created = super().subplots(*args, **subplot_kwargs)
            axes.extend(created.flat)
            return created

    monkeypatch.setattr(render_module, "Figure", SpyFigure)
    render_chart(**kwargs)
    return axes


def _row(key, total=1000.0, **overrides):
    row = {
        "key": key,
        "invoiceCount": 4,
        "totalAmount": total,
        "averageAmount": total / 4,
        "openAmount": total / 2,
        "overdueAmount": total / 4,
        "averageDaysToPay": 12.5,
    }
    return row | overrides


def _currency(code, rows):
    return {"currency": code, "groupCount": len(rows), "rows": rows}


PERIODS = [_currency("USD", [_row("2019-01-01"), _row("2019-02-01", 2000.0), _row("2019-03-01", 500.0)])]
RANKING = [_currency("USD", [_row("C1", 900.0) | {"label": "Acme"}, _row("C2", 300.0) | {"label": "Globex"}])]


@pytest.mark.parametrize(
    ("currencies", "chart_type", "group_by"),
    [
        (PERIODS, ChartType.LINE, GroupBy.MONTH),
        (PERIODS, ChartType.BAR, GroupBy.MONTH),
        (RANKING, ChartType.BAR, GroupBy.CUSTOMER),
        (RANKING, ChartType.STACKED, GroupBy.CUSTOMER),
        ([_currency("USD", [_row(None)])], ChartType.STACKED, None),
    ],
    ids=["line_periods", "bar_periods", "bar_ranking", "stacked_ranking", "stacked_totals"],
)
def test_renderChart_supportedCombination_returnsAPngUnderTheSizeCap(currencies, chart_type, group_by):
    # Arrange / Act
    image = render_chart(
        currencies=currencies,
        chart_type=chart_type,
        metric=ChartMetric.TOTAL,
        group_by=group_by,
        title="Invoiced",
    )

    # Assert
    assert image.startswith(PNG_MAGIC) and len(image) < MAX_CHART_BYTES


# USD and CAD get their own axes and their own scale: the pipeline never compares
# currencies, so neither may the picture.
def test_renderChart_severalCurrencies_drawsOneUnsharedAxisEach(monkeypatch):
    # Arrange / Act
    drawn = _drawn_axes(
        monkeypatch,
        currencies=[_currency("USD", [_row("C1", 900.0)]), _currency("CAD", [_row("C1", 3.0)])],
        chart_type=ChartType.BAR,
        metric=ChartMetric.TOTAL,
        group_by=GroupBy.CUSTOMER,
        title="Invoiced",
    )

    # Assert
    assert [axis.get_title(loc="left") for axis in drawn] == ["USD", "CAD"]
    assert drawn[0].get_xlim() != drawn[1].get_xlim()


@pytest.mark.parametrize(
    "currencies",
    [[], [_currency("USD", []), _currency("CAD", [])]],
    ids=["no_currencies", "all_currencies_empty"],
)
def test_renderChart_noRows_returnsNone(currencies):
    # Arrange / Act
    image = render_chart(
        currencies=currencies,
        chart_type=ChartType.BAR,
        metric=ChartMetric.TOTAL,
        group_by=GroupBy.CUSTOMER,
        title="Invoiced",
    )

    # Assert
    assert image is None


# averageDaysToPay is null when every invoice in a group is still open. Drawing it
# as zero would read as "paid the same day", so the row goes, and a currency left
# with no rows loses its panel rather than showing an empty one.
def test_renderChart_nullMetricRows_areDroppedWithTheirCurrency(monkeypatch):
    # Arrange / Act
    drawn = _drawn_axes(
        monkeypatch,
        currencies=[
            _currency("USD", [_row("C1", averageDaysToPay=None)]),
            _currency("CAD", [_row("C2", averageDaysToPay=8.0), _row("C3", averageDaysToPay=None)]),
        ],
        chart_type=ChartType.BAR,
        metric=ChartMetric.AVERAGE_DAYS_TO_PAY,
        group_by=GroupBy.CUSTOMER,
        title="Days to pay",
    )

    # Assert
    assert [axis.get_title(loc="left") for axis in drawn] == ["CAD"]
    assert [label.get_text() for label in drawn[0].get_yticklabels()] == ["C2"]


# The segments are derived in the app, not by the model: openAmount is part of
# totalAmount and overdueAmount is part of openAmount, so they must be subtracted
# before stacking or the bar would double-count the same money.
@pytest.mark.parametrize(
    ("row", "expected"),
    [
        ({"totalAmount": 100.0, "openAmount": 40.0, "overdueAmount": 10.0}, (60.0, 30.0, 10.0)),
        ({"totalAmount": 100.0, "openAmount": 100.0, "overdueAmount": 100.0}, (0.0, 0.0, 100.0)),
        ({"totalAmount": 100.0, "openAmount": 0.0, "overdueAmount": 0.0}, (100.0, 0.0, 0.0)),
        ({"totalAmount": 100.0, "openAmount": 100.01, "overdueAmount": 0.0}, (0.0, 100.01, 0.0)),
        ({"totalAmount": 100.0, "openAmount": None, "overdueAmount": None}, (100.0, 0.0, 0.0)),
    ],
    ids=["part_open_part_overdue", "all_overdue", "all_cleared", "rounding_overshoot", "missing_fields"],
)
def test_segments_row_splitsTheTotalWithoutDoubleCounting(row, expected):
    # Arrange / Act
    result = _segments(row)

    # Assert
    assert result == expected
    assert all(value >= 0 for value in result)
