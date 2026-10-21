from uuid import uuid4

import pyarrow as pa
import pytest

from lake.settings import LakeSettings, Layer
from lake.storage import Lake, build_storage_options

SCHEMA = pa.schema([("id", pa.int64()), ("name", pa.string())])


def _table(start, count):
    ids = list(range(start, start + count))
    return pa.table({"id": ids, "name": [f"n{i}" for i in ids]}, schema=SCHEMA)


@pytest.fixture
def lake():
    # Arrange: every test gets its own root, because fsspec's memory filesystem is one process-wide store
    root = f"memory://lake-{uuid4().hex}"
    return Lake(LakeSettings(layer_uris={layer: f"{root}/{layer}" for layer in Layer}))


@pytest.mark.parametrize(
    ("settings", "uri", "expected"),
    [
        (LakeSettings(layer_uris={}, endpoint="http://x:3900", key_id="k"), "file:///tmp/lake", {}),
        (LakeSettings(layer_uris={}, endpoint="http://x:3900", key_id="k"), "memory://lake", {}),
        (
            LakeSettings(
                layer_uris={}, endpoint="http://127.0.0.1:3900", region="garage", addressing_style="path", key_id="GK", secret="s"
            ),
            "s3://lake-bronze",
            {
                "endpoint_url": "http://127.0.0.1:3900",
                "key": "GK",
                "secret": "s",
                "client_kwargs": {"region_name": "garage"},
                "config_kwargs": {"s3": {"addressing_style": "path"}},
            },
        ),
        (
            LakeSettings(layer_uris={}, region="eu-central-1", addressing_style="virtual"),
            "s3://acme-lake-bronze",
            {"client_kwargs": {"region_name": "eu-central-1"}, "config_kwargs": {"s3": {"addressing_style": "virtual"}}},
        ),
        (
            LakeSettings(layer_uris={}, kms_key_id="alias/lake"),
            "s3://acme-lake-gold",
            {"s3_additional_kwargs": {"ServerSideEncryption": "aws:kms", "SSEKMSKeyId": "alias/lake"}},
        ),
    ],
    ids=["local_file", "memory", "garage", "aws_iam_role", "aws_kms"],
)
def test_build_storage_options_only_s3_uris_get_s3_options(settings, uri, expected):
    # Arrange / Act
    options = build_storage_options(settings, uri)

    # Assert
    assert options == expected


def test_replace_partition_writes_one_part_per_chunk_and_counts_rows(lake):
    # Arrange
    chunks = [_table(0, 3), _table(3, 2)]

    # Act
    rows = lake.replace_partition(Layer.BRONZE, "invoices", "changed_at=2026-10-16-14", chunks)

    # Assert
    files = lake.list_part_files(Layer.BRONZE, "invoices")
    assert (rows, [file.rsplit("/", 1)[-1] for file in files]) == (5, ["part-00000.parquet", "part-00001.parquet"])
    assert lake.read_dataset(Layer.BRONZE, "invoices")["id"].to_pylist() == [0, 1, 2, 3, 4]


# A rerun of the same partition must replace its files, never add a second copy of the rows.
def test_replace_partition_rerun_replaces_instead_of_appending(lake):
    # Arrange
    lake.replace_partition(Layer.BRONZE, "invoices", "p1", [_table(0, 3), _table(3, 3)])

    # Act
    rows = lake.replace_partition(Layer.BRONZE, "invoices", "p1", [_table(10, 2)])

    # Assert
    assert (rows, lake.read_dataset(Layer.BRONZE, "invoices")["id"].to_pylist()) == (2, [10, 11])


def test_replace_partition_empty_chunks_leave_no_partition(lake):
    # Arrange
    lake.replace_partition(Layer.BRONZE, "invoices", "p1", [_table(0, 3)])

    # Act
    rows = lake.replace_partition(Layer.BRONZE, "invoices", "p1", [_table(0, 0), SCHEMA.empty_table()])

    # Assert
    assert (rows, lake.list_partitions(Layer.BRONZE, "invoices")) == (0, [])


def test_replace_partition_with_an_empty_schema_keeps_a_schema_only_file(lake):
    # Arrange
    lake.replace_partition(Layer.BRONZE, "invoices", "p1", [_table(0, 3)])

    # Act
    rows = lake.replace_partition(Layer.BRONZE, "invoices", "p1", [_table(0, 0)], empty_schema=SCHEMA)

    # Assert
    assert (rows, lake.list_partitions(Layer.BRONZE, "invoices")) == (0, ["p1"])
    assert lake.read_part_schemas(Layer.BRONZE, "invoices") == [SCHEMA]
    assert lake.read_dataset(Layer.BRONZE, "invoices").num_rows == 0


def test_replace_partition_accepts_record_batches(lake):
    # Arrange
    batches = _table(0, 4).to_batches(max_chunksize=2)

    # Act
    rows = lake.replace_partition(Layer.SILVER, "invoices", "p1", batches)

    # Assert
    assert (rows, len(lake.list_part_files(Layer.SILVER, "invoices"))) == (4, 2)


@pytest.mark.parametrize(
    ("batch_size", "expected_sizes"),
    [(100, [100, 100, 50]), (1_000, [250])],
    ids=["smaller_than_a_part", "larger_than_a_part"],
)
def test_iter_batches_streams_at_most_batch_size_rows_at_a_time(lake, batch_size, expected_sizes):
    # Arrange
    lake.replace_partition(Layer.BRONZE, "invoices", "p1", [_table(0, 250)])

    # Act
    sizes = [batch.num_rows for batch in lake.iter_batches(Layer.BRONZE, "invoices", batch_size=batch_size)]

    # Assert
    assert sizes == expected_sizes


def test_iter_batches_reads_only_the_requested_columns_and_partitions(lake):
    # Arrange
    lake.replace_partition(Layer.BRONZE, "invoices", "p1", [_table(0, 2)])
    lake.replace_partition(Layer.BRONZE, "invoices", "p2", [_table(10, 2)])

    # Act
    batches = list(lake.iter_batches(Layer.BRONZE, "invoices", partitions=["p2"], columns=["id"]))

    # Assert
    table = pa.Table.from_batches(batches)
    assert (table.column_names, table["id"].to_pylist()) == (["id"], [10, 11])


@pytest.mark.parametrize(
    ("schema", "expected_columns"),
    [(SCHEMA, ["id", "name"]), (None, [])],
    ids=["with_schema", "without_schema"],
)
def test_read_dataset_nothing_stored_returns_an_empty_table(lake, schema, expected_columns):
    # Arrange / Act
    table = lake.read_dataset(Layer.GOLD, "fact_invoice", schema=schema)

    # Assert
    assert (table.num_rows, table.column_names) == (0, expected_columns)


def test_list_partitions_sorted_and_scoped_to_dataset_and_layer(lake):
    # Arrange
    for partition in ("changed_at=2026-10-16-15", "changed_at=2026-10-16-14"):
        lake.replace_partition(Layer.BRONZE, "invoices", partition, [_table(0, 1)])
    lake.replace_partition(Layer.BRONZE, "customers", "p9", [_table(0, 1)])
    lake.replace_partition(Layer.SILVER, "invoices", "p8", [_table(0, 1)])

    # Act
    partitions = lake.list_partitions(Layer.BRONZE, "invoices")

    # Assert
    assert partitions == ["changed_at=2026-10-16-14", "changed_at=2026-10-16-15"]


@pytest.mark.parametrize(
    ("written", "expected"),
    [({"version": "run-7"}, {"version": "run-7"}), (None, None)],
    ids=["written", "never_written"],
)
def test_read_pointer_returns_what_was_written_or_none(lake, written, expected):
    # Arrange
    if written is not None:
        lake.write_pointer(Layer.GOLD, "_current.json", written)

    # Act
    pointer = lake.read_pointer(Layer.GOLD, "_current.json")

    # Assert
    assert pointer == expected


def test_read_part_schemas_returns_one_schema_per_part_file(lake):
    # Arrange
    lake.replace_partition(Layer.BRONZE, "invoices", "p1", [_table(0, 2), _table(2, 2)])

    # Act
    schemas = lake.read_part_schemas(Layer.BRONZE, "invoices")

    # Assert
    assert [schema.equals(SCHEMA) for schema in schemas] == [True, True]


def test_read_files_reads_the_listed_files_relative_to_the_layer(lake):
    # Arrange
    lake.replace_partition(Layer.GOLD, "dim", "v=1", [_table(0, 2)])
    lake.replace_partition(Layer.GOLD, "dim", "v=2", [_table(10, 3)])
    files = [lake.to_relative(Layer.GOLD, file) for file in lake.list_part_files(Layer.GOLD, "dim", ["v=2"])]

    # Act
    table = lake.read_files(Layer.GOLD, files, SCHEMA)

    # Assert
    assert files == ["dim/v=2/part-00000.parquet"]
    assert table["id"].to_pylist() == [10, 11, 12]


def test_read_files_without_files_returns_an_empty_table_with_the_schema(lake):
    # Arrange / Act
    table = lake.read_files(Layer.GOLD, [], SCHEMA)

    # Assert
    assert (table.num_rows, table.schema) == (0, SCHEMA)


def test_delete_partition_removes_only_that_partition_and_ignores_a_missing_one(lake):
    # Arrange
    lake.replace_partition(Layer.GOLD, "dim", "v=1", [_table(0, 1)])
    lake.replace_partition(Layer.GOLD, "dim", "v=2", [_table(0, 1)])

    # Act
    lake.delete_partition(Layer.GOLD, "dim", "v=1")
    lake.delete_partition(Layer.GOLD, "dim", "v=9")

    # Assert
    assert lake.list_partitions(Layer.GOLD, "dim") == ["v=2"]
