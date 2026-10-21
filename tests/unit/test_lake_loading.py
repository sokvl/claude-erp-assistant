from uuid import uuid4

import pyarrow as pa
import pytest

from lake.loading import Target, load_partition
from lake_config.settings import LakeSettings, Layer
from lake.storage import Lake

TARGET = Target(Layer.SILVER, "invoices", "posting_month=2026-10")


@pytest.fixture
def lake():
    # Arrange: a fresh in-memory lake per test
    root = f"memory://loading-{uuid4().hex}"
    return Lake(LakeSettings(layer_uris={layer: f"{root}/{layer}" for layer in Layer}))


def _to_table(numbers):
    return pa.table({"n": list(numbers)})


def test_load_partition_transforms_every_batch_into_the_target(lake):
    # Arrange
    batches = [(1, 2), (3,), (4, 5)]

    # Act
    rows = load_partition(lake, TARGET, batches, _to_table)

    # Assert
    assert rows == 5
    assert lake.read_dataset(TARGET.layer, TARGET.dataset, [TARGET.partition])["n"].to_pylist() == [1, 2, 3, 4, 5]
    assert len(lake.list_part_files(TARGET.layer, TARGET.dataset)) == 3


# Each batch is pulled, transformed and written before the next one is read, so a partition
# far larger than memory still loads.
def test_load_partition_pulls_one_batch_at_a_time(lake):
    # Arrange
    events = []

    def batches():
        for index in range(3):
            events.append(f"read {index}")
            yield (index,)

    def transform(batch):
        events.append(f"transform {batch[0]}")
        return _to_table(batch)

    # Act
    load_partition(lake, TARGET, batches(), transform)

    # Assert
    assert events == ["read 0", "transform 0", "read 1", "transform 1", "read 2", "transform 2"]


def test_load_partition_no_batches_leaves_no_partition(lake):
    # Arrange / Act
    rows = load_partition(lake, TARGET, [], _to_table)

    # Assert
    assert (rows, lake.list_partitions(TARGET.layer, TARGET.dataset)) == (0, [])


def test_load_partition_no_batches_with_an_empty_schema_marks_the_partition(lake):
    # Arrange
    target = Target(TARGET.layer, TARGET.dataset, TARGET.partition, empty_schema=pa.schema([("n", pa.int64())]))

    # Act
    rows = load_partition(lake, target, [], _to_table)

    # Assert
    assert (rows, lake.list_partitions(target.layer, target.dataset)) == (0, [target.partition])
