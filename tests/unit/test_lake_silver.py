from datetime import UTC, datetime
from uuid import uuid4

import pandas as pd
import pytest

from lake.bronze import DATASET as BRONZE_DATASET
from lake.bronze import to_table
from lake.settings import LakeSettings, Layer
from lake.silver import (
    INVOICE_SCHEMA,
    INVOICES,
    LINES,
    PROCESSED,
    REJECTED,
    REJECTED_LINES,
    STATE,
    derive,
    explode_lines,
    find_pending,
    find_winning_months,
    flatten_invoices,
    keep_latest,
    keep_latest_lines,
    merge_silver,
    standardize,
    validate,
)
from lake.storage import Lake

EXTRACTED = datetime(2026, 10, 16, 1, tzinfo=UTC)
LATER = datetime(2026, 10, 19, 7, tzinfo=UTC)
POSTED = datetime(2026, 9, 1)


def _line(no, total, sku="LAP-DELL-7450"):
    return {"lineNo": no, "sku": sku, "productName": "Latitude 7450", "brand": "Dell", "category": "Laptop",
            "quantity": 1, "unitPrice": total, "lineTotal": total}


def _invoice(key="S000000008", amount=100.0, lines=None, updated=datetime(2026, 10, 15, 14, 42), **changes):
    dates = {"postingDate": POSTED, "documentCreateDate": POSTED, "documentCreateDate1": POSTED,
             "dueInDate": datetime(2026, 9, 16), "baselineCreateDate": POSTED, "clearDate": None}
    dates.update(changes.pop("dates", {}))
    document = {
        "_id": key, "invoiceId": key, "docId": key, "businessCode": "U001",
        "customer": {"number": "0200769623", "name": "GENE in", "nameLower": "gene in"},
        "currency": "USD", "documentType": "RV", "postingId": 1, "isOpen": True,
        "amounts": {"totalOpen": amount}, "dates": dates, "paymentTerms": "NAA8", "businessYear": 2026,
        "lines": [_line(1, amount)] if lines is None else lines, "source": "synthetic", "updatedAt": updated,
    }
    return {**document, **changes}


def _bronze(*documents, extracted_at=EXTRACTED):
    return to_table(documents, extracted_at)


def _silver(*bronze_tables):
    invoices = pd.concat([flatten_invoices(table) for table in bronze_tables], ignore_index=True)
    lines = pd.concat([explode_lines(table) for table in bronze_tables], ignore_index=True)
    latest = keep_latest(invoices)
    return derive(standardize(latest)), keep_latest_lines(lines, latest)


def test_flatten_invoices_names_every_column_and_keeps_dates_in_utc():
    # Arrange / Act
    frame = flatten_invoices(_bronze(_invoice()))

    # Assert
    row = frame.iloc[0]
    assert (row["invoice_id"], row["customer_number"], row["customer_name"], row["amount"]) == (
        "S000000008", "0200769623", "GENE in", 100.0
    )
    assert row["posting_date"] == pd.Timestamp("2026-09-01", tz="UTC")
    assert "lines" not in frame.columns and "invoiceId" not in frame.columns


def test_explode_lines_gives_one_row_per_line_with_its_invoice():
    # Arrange
    bronze = _bronze(_invoice("S1", 30.0, [_line(1, 10.0), _line(2, 20.0)]), _invoice("S2", 5.0, [_line(1, 5.0)]))

    # Act
    lines = explode_lines(bronze)

    # Assert
    assert lines[["invoice_id", "line_no", "line_total", "posting_month"]].values.tolist() == [
        ["S1", 1, 10.0, "2026-09"], ["S1", 2, 20.0, "2026-09"], ["S2", 1, 5.0, "2026-09"]
    ]


def test_explode_lines_empty_bronze_gives_no_lines():
    # Arrange / Act
    lines = explode_lines(_bronze())

    # Assert
    assert lines.empty


# S000000008 sits in bronze twice: open from the first load, closed from the hour it was closed.
@pytest.mark.parametrize("closed_first", [False, True], ids=["read_in_time_order", "read_out_of_order"])
def test_keep_latest_keeps_the_newest_version_whatever_the_read_order(closed_first):
    # Arrange
    opened = _bronze(_invoice())
    closed = _bronze(_invoice(isOpen=False, updated=datetime(2026, 10, 19, 6, 51), closedAt=datetime(2026, 10, 19, 6, 51)), extracted_at=LATER)
    tables = [closed, opened] if closed_first else [opened, closed]

    # Act
    latest = keep_latest(pd.concat([flatten_invoices(table) for table in tables], ignore_index=True))

    # Assert
    assert latest[["invoice_id", "is_open", "closed_at"]].values.tolist() == [["S000000008", False, pd.Timestamp("2026-10-19 06:51", tz="UTC")]]


# The overlap and reruns can land the very same version twice; the later extraction decides.
def test_keep_latest_tie_on_updated_at_goes_to_the_later_extraction():
    # Arrange
    first = flatten_invoices(_bronze(_invoice(amount=100.0)))
    again = flatten_invoices(_bronze(_invoice(amount=100.0), extracted_at=LATER))

    # Act
    latest = keep_latest(pd.concat([again, first], ignore_index=True))

    # Assert
    assert (len(latest), latest.iloc[0]["extracted_at"]) == (1, pd.Timestamp(LATER))


# invoiceId is null on six real invoices; keyed on it they would collapse into one row.
def test_keep_latest_keys_on_id_so_invoices_without_invoice_id_all_survive():
    # Arrange
    documents = [_invoice(f"19304{i}", invoiceId=None) for i in range(3)]

    # Act
    latest = keep_latest(flatten_invoices(_bronze(*documents)))

    # Assert
    assert sorted(latest["invoice_id"]) == ["193040", "193041", "193042"]


def test_keep_latest_lines_follow_the_kept_version():
    # Arrange
    opened = _bronze(_invoice(amount=30.0, lines=[_line(1, 10.0), _line(2, 20.0)]))
    reissued = _bronze(_invoice(amount=30.0, lines=[_line(1, 30.0, sku="SRV-DELL-R660")], updated=datetime(2026, 10, 19, 6)), extracted_at=LATER)

    # Act
    _, lines = _silver(opened, reissued)

    # Assert
    assert lines[["line_no", "sku", "line_total"]].values.tolist() == [[1, "SRV-DELL-R660", 30.0]]


# Replaying merged bronze brings the version silver already holds; its lines must not double.
def test_keep_latest_lines_same_version_twice_keeps_each_line_once():
    # Arrange
    bronze = _bronze(_invoice(amount=30.0, lines=[_line(1, 10.0), _line(2, 20.0)]))
    lines = pd.concat([explode_lines(bronze), explode_lines(bronze)], ignore_index=True)

    # Act
    kept = keep_latest_lines(lines, keep_latest(flatten_invoices(bronze)))

    # Assert
    assert kept["line_total"].tolist() == [10.0, 20.0]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(" GENE in ", "GENE in"), ("US  systems", "US systems"), ("\tWAL-MAR\n corp ", "WAL-MAR corp")],
    ids=["outer_spaces", "double_space_inside", "tabs_and_newlines"],
)
def test_standardize_collapses_whitespace_in_customer_names(raw, expected):
    # Arrange
    frame = flatten_invoices(_bronze(_invoice(customer={"number": "1", "name": raw, "nameLower": raw.lower()})))

    # Act
    name = standardize(frame).iloc[0]["customer_name"]

    # Assert
    assert name == expected


def test_standardize_upper_cases_the_currency():
    # Arrange / Act
    frame = standardize(flatten_invoices(_bronze(_invoice(currency=" cad"))))

    # Assert
    assert frame.iloc[0]["currency"] == "CAD"


# Comparing with NaT is always False, so an unpaid invoice must get <NA>, never False: otherwise
# every open invoice would count as paid on time.
@pytest.mark.parametrize(
    ("changes", "days_to_pay", "paid_late"),
    [
        ({"isOpen": False, "dates": {"clearDate": datetime(2026, 9, 10)}}, 9, False),
        ({"isOpen": False, "dates": {"clearDate": datetime(2026, 9, 30)}}, 29, True),
        ({}, pd.NA, pd.NA),
        ({"isOpen": False, "closedAt": datetime(2026, 10, 19, 6, 51)}, pd.NA, pd.NA),
    ],
    ids=["paid_on_time", "paid_late", "still_open", "closed_in_app_without_payment_date"],
)
def test_derive_payment_fields_only_for_invoices_with_a_payment_date(changes, days_to_pay, paid_late):
    # Arrange
    frame = flatten_invoices(_bronze(_invoice(**changes)))

    # Act
    row = derive(frame).iloc[0]

    # Assert
    assert (row["days_to_pay"] is pd.NA or row["days_to_pay"] == days_to_pay) and str(row["days_to_pay"]) == str(days_to_pay)
    assert str(row["paid_late"]) == str(paid_late)
    assert row["posting_month"] == "2026-09"


# MongoDB's $dateDiff counts midnights crossed; plain timedelta days would say 0 here.
def test_derive_days_to_pay_counts_calendar_days_like_mongo():
    # Arrange
    frame = flatten_invoices(_bronze(_invoice(isOpen=False, dates={"postingDate": datetime(2026, 9, 1, 23, 30),
                                                                  "clearDate": datetime(2026, 9, 2, 0, 30)})))

    # Act
    row = derive(frame).iloc[0]

    # Assert
    assert row["days_to_pay"] == 1


def test_validate_clean_invoice_is_accepted_without_flags():
    # Arrange
    invoices, lines = _silver(_bronze(_invoice()))

    # Act
    result = validate(invoices, lines)

    # Assert
    assert (len(result.invoices), len(result.rejected), result.invoices.iloc[0]["quality_flags"]) == (1, 0, [])


@pytest.mark.parametrize(
    ("changes", "reasons"),
    [
        ({"amount": 0.0, "lines": [_line(1, 0.0)]}, ["amount_not_positive"]),
        ({"currency": "US"}, ["invalid_currency"]),
        ({"isOpen": False, "dates": {"clearDate": datetime(2026, 8, 1)}}, ["cleared_before_posting"]),
        ({"dates": {"clearDate": datetime(2026, 9, 10)}}, ["open_with_clear_date"]),
        ({"amount": -5.0, "currency": "usd1", "lines": [_line(1, -5.0)]}, ["amount_not_positive", "invalid_currency"]),
    ],
    ids=["zero_amount", "bad_currency", "cleared_before_posting", "open_but_paid", "several_reasons"],
)
def test_validate_hard_rule_moves_the_invoice_to_rejected_with_its_reasons(changes, reasons):
    # Arrange
    invoices, lines = _silver(_bronze(_invoice(**changes)))

    # Act
    result = validate(invoices, lines)

    # Assert
    assert (len(result.invoices), result.rejected.iloc[0]["rejection_reasons"]) == (0, reasons)


@pytest.mark.parametrize(
    ("changes", "flags"),
    [
        ({"dates": {"dueInDate": datetime(2026, 8, 20)}}, ["due_before_posting"]),
        ({"isOpen": False, "closedAt": datetime(2026, 10, 19)}, ["closed_without_payment_date"]),
        ({"amount": 100.0, "lines": [_line(1, 60.0)]}, ["lines_do_not_match_amount"]),
        ({"amount": 100.0, "lines": []}, ["lines_do_not_match_amount"]),
    ],
    ids=["due_before_posting", "closed_in_app", "lines_sum_differs", "no_lines_at_all"],
)
def test_validate_soft_rule_keeps_the_invoice_and_flags_it(changes, flags):
    # Arrange
    invoices, lines = _silver(_bronze(_invoice(**changes)))

    # Act
    result = validate(invoices, lines)

    # Assert
    assert (len(result.rejected), result.invoices.iloc[0]["quality_flags"]) == (0, flags)


# A mismatch is never repaired by overwriting: the header amount is what the customer owes.
def test_validate_mismatch_keeps_the_header_amount_and_shows_the_lines_total():
    # Arrange
    invoices, lines = _silver(_bronze(_invoice(amount=100.0, lines=[_line(1, 60.0), _line(2, 30.0)])))

    # Act
    row = validate(invoices, lines).invoices.iloc[0]

    # Assert
    assert (row["amount"], row["lines_total"]) == (100.0, 90.0)


def test_validate_amount_within_a_cent_of_the_lines_is_not_a_mismatch():
    # Arrange
    invoices, lines = _silver(_bronze(_invoice(amount=100.0, lines=[_line(1, 33.33), _line(2, 66.66)])))

    # Act
    flags = validate(invoices, lines).invoices.iloc[0]["quality_flags"]

    # Assert
    assert flags == []


# Who closed an invoice and why lives in the audit log for management; silver, which feeds the
# analyst through gold, keeps only the state, even though old bronze files still carry the reason.
def test_flatten_invoices_drops_the_close_reason_from_silver():
    # Arrange / Act
    frame = flatten_invoices(_bronze(_invoice(isOpen=False, closedReason="paid by wire")))

    # Assert
    assert "closed_reason" not in frame.columns


@pytest.fixture
def lake():
    # Arrange: every test gets its own root, because fsspec's memory filesystem is one process-wide store
    root = f"memory://silver-{uuid4().hex}"
    return Lake(LakeSettings(layer_uris={layer: f"{root}/{layer}" for layer in Layer}))


def _land(lake, hour, *documents, extracted_at=EXTRACTED):
    lake.replace_partition(Layer.BRONZE, BRONZE_DATASET, f"changed_at={hour}", [_bronze(*documents, extracted_at=extracted_at)])


def _read(lake, dataset, month=None):
    partitions = None if month is None else [f"posting_month={month}"]
    return lake.read_dataset(Layer.SILVER, dataset, partitions).to_pandas()


def _closed(key="S1", **changes):
    return _invoice(key, isOpen=False, updated=datetime(2026, 10, 19, 6, 51),
                    dates={"clearDate": datetime(2026, 9, 10)}, **changes)


# Dagster can materialize a failed hour again after later ones succeeded; a "last partition"
# pointer would skip it forever, a set of processed names does not.
@pytest.mark.parametrize(
    ("bronze", "processed", "expected"),
    [
        (["changed_at=2026-10-16-00", "changed_at=2026-10-16-01"], [], ["changed_at=2026-10-16-00", "changed_at=2026-10-16-01"]),
        (["changed_at=2026-10-16-00", "changed_at=2026-10-16-01"], ["changed_at=2026-10-16-00"], ["changed_at=2026-10-16-01"]),
        (["changed_at=2026-10-16-00", "changed_at=2026-10-16-01", "changed_at=2026-10-16-02"],
         ["changed_at=2026-10-16-00", "changed_at=2026-10-16-02"], ["changed_at=2026-10-16-01"]),
        (["changed_at=2026-10-16-00"], ["changed_at=2026-10-16-00"], []),
    ],
    ids=["first_run", "next_hour", "hour_landed_late", "nothing_new"],
)
def test_find_pending_returns_every_bronze_partition_not_processed_yet(bronze, processed, expected):
    # Arrange / Act
    pending = find_pending(bronze, processed)

    # Assert
    assert pending == expected


def _locations(*rows):
    return pd.DataFrame(rows, columns=["invoice_id", "updated_at", "extracted_at", "posting_month"])


OLD = pd.Timestamp("2026-10-15", tz="UTC")
NEW = pd.Timestamp("2026-10-19", tz="UTC")


# The month an invoice lives in is decided by its newest version, wherever each version sits.
@pytest.mark.parametrize(
    ("stored", "arriving", "expected"),
    [
        (_locations(), _locations(("S1", NEW, NEW, "2026-09")), "2026-09"),
        (_locations(("S1", OLD, OLD, "2026-09")), _locations(("S1", NEW, NEW, "2026-10")), "2026-10"),
        (_locations(("S1", NEW, NEW, "2026-10")), _locations(("S1", OLD, NEW, "2026-09")), "2026-10"),
    ],
    ids=["new_invoice", "newer_version_moved_month", "replayed_older_version_loses"],
)
def test_find_winning_months_follows_the_newest_version(stored, arriving, expected):
    # Arrange / Act
    months = find_winning_months(arriving, stored)

    # Assert
    assert months.to_dict() == {"S1": expected}


def test_merge_silver_first_run_writes_one_partition_per_posting_month(lake):
    # Arrange
    _land(lake, "2026-10-16-00", _invoice("S1"), _invoice("S2", dates={"postingDate": datetime(2026, 8, 5)}))

    # Act
    run = merge_silver(lake)

    # Assert
    assert (run.bronze_partitions, run.months, run.invoices, run.rejected) == (
        ["changed_at=2026-10-16-00"], ["2026-08", "2026-09"], 2, 0
    )
    assert lake.list_partitions(Layer.SILVER, INVOICES) == ["posting_month=2026-08", "posting_month=2026-09"]
    assert lake.read_pointer(Layer.SILVER, STATE) == {PROCESSED: ["changed_at=2026-10-16-00"]}


def test_merge_silver_without_new_bronze_does_nothing(lake):
    # Arrange
    _land(lake, "2026-10-16-00", _invoice("S1"))
    merge_silver(lake)

    # Act
    run = merge_silver(lake)

    # Assert
    assert (run.bronze_partitions, run.months) == ([], [])
    assert len(_read(lake, INVOICES)) == 1


# Closing one September invoice must cost one month of rewriting, not the whole history.
def test_merge_silver_change_rewrites_only_the_month_it_touches(lake):
    # Arrange
    _land(lake, "2026-10-16-00", _invoice("S1"), _invoice("S2", dates={"postingDate": datetime(2026, 8, 5)}))
    merge_silver(lake)
    august_files = lake.list_part_files(Layer.SILVER, INVOICES, ["posting_month=2026-08"])
    _land(lake, "2026-10-19-06", _closed("S1"), extracted_at=LATER)

    # Act
    run = merge_silver(lake)

    # Assert
    september = _read(lake, INVOICES, "2026-09")
    assert run.months == ["2026-09"]
    assert september[["invoice_id", "is_open", "days_to_pay"]].values.tolist() == [["S1", False, 9]]
    assert lake.list_part_files(Layer.SILVER, INVOICES, ["posting_month=2026-08"]) == august_files


# The state is written last, so a crash replays bronze already merged; replaying must change nothing.
def test_merge_silver_replaying_processed_bronze_gives_the_same_silver(lake):
    # Arrange
    _land(lake, "2026-10-16-00", _invoice("S1", lines=[_line(1, 40.0), _line(2, 60.0)]))
    _land(lake, "2026-10-19-06", _closed("S1", lines=[_line(1, 40.0), _line(2, 60.0)]), extracted_at=LATER)
    merge_silver(lake)
    before = (_read(lake, INVOICES), _read(lake, LINES))
    lake.write_pointer(Layer.SILVER, STATE, {PROCESSED: []})

    # Act
    merge_silver(lake)

    # Assert
    pd.testing.assert_frame_equal(_read(lake, INVOICES), before[0])
    pd.testing.assert_frame_equal(_read(lake, LINES), before[1])


# A posting date never changes in the app, but if bad data moves one, silver must not count the
# invoice in both months.
def test_merge_silver_invoice_moving_month_leaves_its_old_month(lake):
    # Arrange
    _land(lake, "2026-10-16-00", _invoice("S1"), _invoice("S2"))
    merge_silver(lake)
    moved = _invoice("S1", updated=datetime(2026, 10, 19, 6), dates={"postingDate": datetime(2026, 10, 1)})
    _land(lake, "2026-10-19-06", moved, extracted_at=LATER)

    # Act
    run = merge_silver(lake)

    # Assert
    assert run.months == ["2026-09", "2026-10"]
    assert _read(lake, INVOICES, "2026-09")["invoice_id"].tolist() == ["S2"]
    assert _read(lake, INVOICES, "2026-10")["invoice_id"].tolist() == ["S1"]
    assert sorted(_read(lake, LINES)["invoice_id"]) == ["S1", "S2"]


# Quarantine is part of a month's current state: reading only the accepted rows would leave the
# bad version behind in quarantine after the fix arrives.
def test_merge_silver_corrected_invoice_leaves_quarantine_with_its_lines(lake):
    # Arrange
    _land(lake, "2026-10-16-00", _invoice("S1", amount=0.0, lines=[_line(1, 0.0)]))
    merge_silver(lake)
    rejected_first = _read(lake, REJECTED)
    corrected = _invoice("S1", amount=50.0, lines=[_line(1, 50.0)], updated=datetime(2026, 10, 19, 6))
    _land(lake, "2026-10-19-06", corrected, extracted_at=LATER)

    # Act
    run = merge_silver(lake)

    # Assert
    assert rejected_first["rejection_reasons"].tolist() == [["amount_not_positive"]]
    assert (run.invoices, run.rejected) == (1, 0)
    assert _read(lake, INVOICES)["amount"].tolist() == [50.0]
    assert _read(lake, LINES)["line_total"].tolist() == [50.0]
    assert _read(lake, REJECTED).empty and _read(lake, REJECTED_LINES).empty


# Every file of a dataset must share one schema, even when no row has a flag to infer types from.
def test_merge_silver_writes_the_declared_schema(lake):
    # Arrange
    _land(lake, "2026-10-16-00", _invoice("S1"))

    # Act
    merge_silver(lake)

    # Assert
    assert lake.read_part_schemas(Layer.SILVER, INVOICES) == [INVOICE_SCHEMA]


def test_merge_silver_month_left_without_invoices_disappears(lake):
    # Arrange
    _land(lake, "2026-10-16-00", _invoice("S1"))
    merge_silver(lake)
    moved = _invoice("S1", updated=datetime(2026, 10, 19, 6), dates={"postingDate": datetime(2026, 10, 1)})
    _land(lake, "2026-10-19-06", moved, extracted_at=LATER)

    # Act
    merge_silver(lake)

    # Assert
    assert lake.list_partitions(Layer.SILVER, INVOICES) == ["posting_month=2026-10"]
    assert lake.list_partitions(Layer.SILVER, LINES) == ["posting_month=2026-10"]


def test_merge_silver_invoice_without_lines_is_kept_and_flagged(lake):
    # Arrange
    _land(lake, "2026-10-16-00", _invoice("S1", lines=[]))

    # Act
    merge_silver(lake)

    # Assert
    assert _read(lake, INVOICES)["quality_flags"].tolist() == [["lines_do_not_match_amount"]]
    assert lake.list_partitions(Layer.SILVER, LINES) == []
