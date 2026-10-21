from datetime import UTC, datetime
from uuid import uuid4

import pandas as pd
import pytest
from pymongo import ReadPreference
from pymongo.read_concern import ReadConcern

from lake.reconciliation import (
    TIMEOUT_MS,
    build_changed_filter,
    build_month_totals_pipeline,
    compare_totals,
    find_changed_ids,
    find_watermark,
    read_mongo_totals,
    reconcile,
    summarize_silver,
)
from lake_config.settings import LakeSettings, Layer
from lake.silver import PROCESSED, STATE
from lake.storage import Lake

FIRST = datetime(2026, 10, 16, tzinfo=UTC)
W = datetime(2026, 10, 19, 6, tzinfo=UTC)


class Invoices:
    def __init__(self, changed=(), totals=()):
        self.changed = list(changed)
        self.totals = list(totals)
        self.options = None
        self.calls = []

    def with_options(self, **options):
        self.options = options
        return self

    def distinct(self, key, criteria, maxTimeMS):
        self.calls.append(("distinct", key, criteria, maxTimeMS))
        return self.changed

    def aggregate(self, pipeline, maxTimeMS):
        self.calls.append(("aggregate", pipeline, maxTimeMS))
        return iter(self.totals)


def _hours(*hours):
    return [f"changed_at=2026-10-16-{hour:02d}" for hour in hours]


def _facts(*rows):
    return pd.DataFrame(rows, columns=["invoice_id", "posting_month", "amount", "is_open"])


def _september(open_ids, closed_ids=()):
    rows = [(key, "2026-09", 10.0, True) for key in open_ids] + [(key, "2026-09", 10.0, False) for key in closed_ids]
    return _facts(*rows)


# Silver knows Mongo only up to the end of the hours merged without a gap: a late hour 05 keeps
# the watermark at 05:00 even when 06 and 07 are merged.
@pytest.mark.parametrize(
    ("processed", "expected"),
    [
        ([], None),
        (_hours(1, 2), None),
        (_hours(0), datetime(2026, 10, 16, 1, tzinfo=UTC)),
        (_hours(0, 1, 2), datetime(2026, 10, 16, 3, tzinfo=UTC)),
        (_hours(0, 1, 2, 3, 4, 6, 7), datetime(2026, 10, 16, 5, tzinfo=UTC)),
    ],
    ids=["nothing_merged", "first_hour_missing", "only_the_history", "contiguous_hours", "hour_five_late"],
)
def test_find_watermark_stops_at_the_first_gap(processed, expected):
    # Arrange / Act
    watermark = find_watermark(processed, FIRST)

    # Assert
    assert watermark == expected


# The changed ids must come from the same snapshot bronze reads: a secondary, majority only.
def test_find_changed_ids_reads_majority_from_a_secondary_with_a_time_limit():
    # Arrange
    invoices = Invoices(changed=["S9", "S7"])

    # Act
    changed = find_changed_ids(invoices, W)

    # Assert
    assert changed == ["S7", "S9"]
    assert invoices.options == {"read_preference": ReadPreference.SECONDARY_PREFERRED, "read_concern": ReadConcern("majority")}
    assert invoices.calls == [("distinct", "_id", build_changed_filter(W), TIMEOUT_MS)]


def test_read_mongo_totals_names_the_month_and_casts_sums_to_integers():
    # Arrange
    invoices = Invoices(totals=[{"_id": "2026-09", "invoices": 2, "amount_cents": 3000.0, "open_invoices": 1}])

    # Act
    totals = read_mongo_totals(invoices, ["S7"])

    # Assert
    assert totals.to_dict("records") == [{"posting_month": "2026-09", "invoices": 2, "amount_cents": 3000, "open_invoices": 1}]
    assert invoices.calls == [("aggregate", build_month_totals_pipeline(["S7"]), TIMEOUT_MS)]


# Each amount is rounded to cents before summing, the same as $round in the pipeline, so float
# noise like 54273.28 * 100 = 5427327.999... never shows up as a one-cent difference.
def test_summarize_silver_counts_cents_invoices_and_open_ones_per_month():
    # Arrange
    facts = _facts(("S1", "2026-09", 54273.28, True), ("S2", "2026-09", 0.1, False), ("S3", "2026-08", None, None))

    # Act
    totals = summarize_silver(facts, [])

    # Assert
    assert totals.to_dict("records") == [
        {"posting_month": "2026-08", "invoices": 1, "amount_cents": 0, "open_invoices": 0},
        {"posting_month": "2026-09", "invoices": 2, "amount_cents": 5427338, "open_invoices": 1},
    ]


# W = 06:00; before any change silver and Mongo agree on 120 open September invoices.
# S7: closed in the app at 06:51, so after W: fresh, silver has not seen it yet, excluded.
# S9: closed by a script at 05:30 that left updatedAt in 2024: silent, stays in, must show up.
# S11: closed in the app at 05:40, already merged: both sides agree.
@pytest.mark.parametrize(
    ("silver_closed", "mongo_closed", "changed_after_w", "mismatch"),
    [
        ([], ["S7"], ["S7"], False),
        ([], ["S9"], [], True),
        (["S11"], ["S11"], [], False),
        ([], ["S7", "S9"], ["S7"], True),
    ],
    ids=["fresh_close_is_cut_off", "silent_close_is_caught", "merged_close_agrees", "silent_close_next_to_a_fresh_one"],
)
def test_compare_totals_after_the_cut_off_only_silent_changes_differ(silver_closed, mongo_closed, changed_after_w, mismatch):
    # Arrange
    ids = [f"S{n}" for n in range(1, 121)]
    silver = summarize_silver(_september([key for key in ids if key not in silver_closed], silver_closed), changed_after_w)
    mongo = summarize_silver(_september([key for key in ids if key not in mongo_closed], mongo_closed), changed_after_w)

    # Act
    differences = compare_totals(silver, mongo)

    # Assert
    assert (not differences.empty) == mismatch


@pytest.mark.parametrize(
    ("silver", "mongo", "expected"),
    [
        (_facts(("S1", "2026-09", 10.0, True)), _facts(), ["2026-09"]),
        (_facts(), _facts(("S1", "2026-09", 10.0, True)), ["2026-09"]),
        (_facts(("S1", "2026-09", 10.0, True)), _facts(("S1", "2026-09", 10.01, True)), ["2026-09"]),
        (_facts(("S1", "2026-09", 10.0, True), ("S2", "2026-08", 5.0, True)), _facts(("S1", "2026-09", 10.0, True), ("S2", "2026-08", 5.0, True)), []),
    ],
    ids=["missing_in_mongo", "missing_in_silver", "one_cent_off", "all_agree"],
)
def test_compare_totals_reports_every_month_that_differs(silver, mongo, expected):
    # Arrange / Act
    differences = compare_totals(summarize_silver(silver, []), summarize_silver(mongo, []))

    # Assert
    assert differences["posting_month"].tolist() == expected


@pytest.fixture
def lake():
    # Arrange: every test gets its own root, because fsspec's memory filesystem is one process-wide store
    root = f"memory://reconciliation-{uuid4().hex}"
    return Lake(LakeSettings(layer_uris={layer: f"{root}/{layer}" for layer in Layer}))


# Without the first hour, silver lacks the history, so no comparison can pass and none is sent.
def test_reconcile_without_the_history_merged_fails_without_asking_mongo(lake):
    # Arrange
    invoices = Invoices()

    # Act
    result = reconcile(lake, invoices, _facts(), FIRST)

    # Assert
    assert (result.watermark, result.excluded, invoices.calls) == (None, [], [])


def test_reconcile_leaves_out_invoices_changed_after_the_watermark_on_both_sides(lake):
    # Arrange
    lake.write_pointer(Layer.SILVER, STATE, {PROCESSED: _hours(0, 1)})
    invoices = Invoices(changed=["S7"], totals=[{"_id": "2026-09", "invoices": 1, "amount_cents": 1000, "open_invoices": 1}])
    facts = _facts(("S1", "2026-09", 10.0, True), ("S7", "2026-09", 10.0, True))

    # Act
    result = reconcile(lake, invoices, facts, FIRST)

    # Assert
    assert (result.watermark, result.excluded) == (datetime(2026, 10, 16, 2, tzinfo=UTC), ["S7"])
    assert result.differences.empty
    assert invoices.calls[1] == ("aggregate", build_month_totals_pipeline(["S7"]), TIMEOUT_MS)
