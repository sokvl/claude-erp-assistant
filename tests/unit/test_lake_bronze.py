from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pymongo import ReadPreference
from pymongo.read_concern import ReadConcern

from lake.bronze import (
    BRONZE_SCHEMA,
    DATASET,
    Window,
    build_filter,
    build_window,
    count_window,
    extract_batches,
    find_unknown_fields,
    load_bronze,
    name_partition,
    to_table,
)
from lake_config.settings import LakeSettings, Layer
from lake.storage import Lake

START = datetime(2026, 10, 16, 14, tzinfo=UTC)
END = START + timedelta(hours=1)
EXTRACTED = datetime(2026, 10, 16, 15, 15, tzinfo=UTC)
POSTED = datetime(2026, 9, 1)


def _invoice(key="S000000001", **overrides):
    document = {
        "_id": key, "invoiceId": key, "docId": key, "businessCode": "U001",
        "customer": {"number": "0200769623", "name": "WAL-MAR corp", "nameLower": "wal-mar corp"},
        "currency": "USD", "documentType": "RV", "postingId": 1, "isOpen": True,
        "amounts": {"totalOpen": 1234.5},
        "dates": {
            "postingDate": POSTED, "documentCreateDate": POSTED, "documentCreateDate1": POSTED,
            "dueInDate": POSTED + timedelta(days=15), "baselineCreateDate": POSTED, "clearDate": None,
        },
        "paymentTerms": "NAA8", "businessYear": 2026,
        "lines": [{"lineNo": 1, "sku": "LAP-DELL-7450", "productName": "Latitude 7450", "brand": "Dell",
                   "category": "Laptop", "quantity": 1, "unitPrice": 1234.5, "lineTotal": 1234.5}],
        "source": "synthetic", "updatedAt": datetime(2026, 10, 16, 14, 30),
    }
    return {**document, **overrides}


class Invoices:
    def __init__(self, documents):
        self.documents = documents
        self.options = None
        self.calls = []

    def with_options(self, **options):
        self.options = options
        return self

    def find(self, criteria, sort, batch_size):
        self.calls.append((criteria, sort, batch_size))
        return iter(self.documents)

    def count_documents(self, criteria):
        self.calls.append((criteria,))
        return len(self.documents)


@pytest.fixture
def lake():
    # Arrange: a fresh in-memory lake per test
    root = f"memory://bronze-{uuid4().hex}"
    return Lake(LakeSettings(layer_uris={layer: f"{root}/{layer}" for layer in Layer}))


# The overlap catches writes committed a little after their updatedAt; the first partition has
# no lower bound so it takes the whole history instead of one partition per hour since 2018.
@pytest.mark.parametrize(
    ("first", "expected"),
    [(False, Window(since=START - timedelta(minutes=5), until=END)), (True, Window(since=None, until=END))],
    ids=["regular_partition", "first_partition"],
)
def test_build_window_overlaps_the_previous_hour_except_the_first(first, expected):
    # Arrange / Act
    window = build_window(START, END, first)

    # Assert
    assert window == expected


@pytest.mark.parametrize(
    ("window", "expected"),
    [
        (Window(since=START, until=END), {"updatedAt": {"$lt": END, "$gte": START}}),
        (Window(since=None, until=END), {"updatedAt": {"$lt": END}}),
    ],
    ids=["bounded", "unbounded_start"],
)
def test_build_filter_bounds_updated_at(window, expected):
    # Arrange / Act / Assert
    assert build_filter(window) == expected


def test_name_partition_uses_the_hour_of_the_window():
    # Arrange / Act / Assert
    assert name_partition(START) == "changed_at=2026-10-16-14"


# Reading from a secondary takes load off the primary; majority makes sure a write that is
# about to be rolled back after a failover never lands in the lake.
def test_extract_batches_reads_majority_from_a_secondary_in_updated_at_order():
    # Arrange
    invoices = Invoices([_invoice(f"S{i}") for i in range(5)])

    # Act
    batches = list(extract_batches(invoices, Window(since=START, until=END), batch_size=2))

    # Assert
    assert [len(batch) for batch in batches] == [2, 2, 1]
    assert invoices.options == {"read_preference": ReadPreference.SECONDARY_PREFERRED, "read_concern": ReadConcern("majority")}
    assert invoices.calls == [({"updatedAt": {"$lt": END, "$gte": START}}, [("updatedAt", 1), ("_id", 1)], 2)]


def test_to_table_keeps_values_and_fills_missing_fields_with_null():
    # Arrange
    closed = _invoice("1930547631", isOpen=False, closedAt=datetime(2026, 9, 30, 11, 1), closedReason="wire received")
    del closed["source"]

    # Act
    rows = to_table([_invoice(), closed], EXTRACTED).to_pylist()

    # Assert
    assert (rows[0]["closedAt"], rows[0]["closedReason"], rows[0]["source"]) == (None, None, "synthetic")
    assert (rows[1]["closedReason"], rows[1]["source"], rows[1]["dates"]["clearDate"]) == ("wire received", None, None)
    assert (rows[0]["lines"][0]["sku"], rows[0]["customer"]["number"], rows[0]["_extracted_at"]) == (
        "LAP-DELL-7450", "0200769623", EXTRACTED
    )


# Mongo stores naive UTC datetimes; the lake marks them as UTC so no reader has to guess.
def test_to_table_reads_naive_mongo_datetimes_as_utc():
    # Arrange / Act
    row = to_table([_invoice()], EXTRACTED).to_pylist()[0]

    # Assert
    assert row["updatedAt"] == datetime(2026, 10, 16, 14, 30, tzinfo=UTC)


# A window with nothing but nulls in a column must not write that column with another type.
@pytest.mark.parametrize("documents", [[], [_invoice()]], ids=["empty", "one_invoice"])
def test_to_table_schema_does_not_depend_on_the_documents(documents):
    # Arrange / Act
    table = to_table(documents, EXTRACTED)

    # Assert
    assert table.schema == BRONZE_SCHEMA


@pytest.mark.parametrize(
    ("document", "expected"),
    [
        (_invoice(), set()),
        (_invoice(priority="high"), {"priority"}),
        (_invoice(customer={"number": "1", "name": "A", "nameLower": "a", "vatId": "PL1"}), {"customer.vatId"}),
        (_invoice(lines=[{**_invoice()["lines"][0], "discount": 0.1}]), {"lines[].discount"}),
    ],
    ids=["known_shape", "new_top_level_field", "new_nested_field", "new_line_field"],
)
def test_find_unknown_fields_reports_fields_the_schema_would_drop(document, expected):
    # Arrange / Act / Assert
    assert find_unknown_fields(document) == expected


def test_load_bronze_writes_the_window_and_reports_its_rows(lake):
    # Arrange
    invoices = Invoices([_invoice(f"S{i}") for i in range(5)])

    # Act
    load = load_bronze(lake, invoices, Window(since=START, until=END), "changed_at=2026-10-16-14", EXTRACTED, batch_size=2)

    # Assert
    assert (load.rows, load.unknown_fields) == (5, [])
    assert len(lake.list_part_files(Layer.BRONZE, DATASET)) == 3
    assert lake.read_dataset(Layer.BRONZE, DATASET)["_id"].to_pylist() == [f"S{i}" for i in range(5)]


def test_load_bronze_rerun_leaves_one_copy_of_each_invoice(lake):
    # Arrange
    window = Window(since=START, until=END)
    load_bronze(lake, Invoices([_invoice("S1"), _invoice("S2")]), window, "p", EXTRACTED)

    # Act
    load_bronze(lake, Invoices([_invoice("S1"), _invoice("S2")]), window, "p", EXTRACTED)

    # Assert
    assert lake.read_dataset(Layer.BRONZE, DATASET)["_id"].to_pylist() == ["S1", "S2"]


# An hour without changes still leaves a schema-only file: silver's watermark needs to tell
# "nothing changed" apart from "never extracted", and only the lake itself can say which.
def test_load_bronze_empty_window_marks_the_hour_with_an_empty_file(lake):
    # Arrange / Act
    load = load_bronze(lake, Invoices([]), Window(since=START, until=END), "p", EXTRACTED)

    # Assert
    assert (load.rows, lake.list_partitions(Layer.BRONZE, DATASET)) == (0, ["p"])
    assert lake.read_part_schemas(Layer.BRONZE, DATASET) == [BRONZE_SCHEMA]
    assert lake.read_dataset(Layer.BRONZE, DATASET).num_rows == 0


def test_load_bronze_reports_unknown_fields_across_batches(lake):
    # Arrange
    invoices = Invoices([_invoice("S1"), _invoice("S2", priority="high"), _invoice("S3", region="EU")])

    # Act
    load = load_bronze(lake, invoices, Window(since=START, until=END), "p", EXTRACTED, batch_size=1)

    # Assert
    assert load.unknown_fields == ["priority", "region"]


# The asset check compares the partition with this count, so both must read the same snapshot:
# same window, same secondary, same majority read concern.
def test_count_window_counts_with_the_same_read_options_as_the_extract():
    # Arrange
    invoices = Invoices([_invoice("S1"), _invoice("S2")])

    # Act
    count = count_window(invoices, Window(since=None, until=END))

    # Assert
    assert count == 2
    assert invoices.options == {"read_preference": ReadPreference.SECONDARY_PREFERRED, "read_concern": ReadConcern("majority")}
    assert invoices.calls == [({"updatedAt": {"$lt": END}},)]
