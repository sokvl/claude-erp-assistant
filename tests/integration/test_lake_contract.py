import os
from uuid import uuid4

import pyarrow as pa
import pytest

from lake_config.settings import LakeConfigError, Layer, Role, load_settings
from lake.storage import Lake, open_location

pytestmark = pytest.mark.lake

TABLE = pa.table({"id": list(range(250)), "name": [f"n{i}" for i in range(250)]})


def _lake(role):
    try:
        return Lake(load_settings(os.environ, role))
    except LakeConfigError as exc:
        if os.environ.get("REQUIRE_LAKE"):
            pytest.fail(f"lake store is not configured: {exc}")
        pytest.skip(f"lake store is not configured: {exc}")


@pytest.fixture
def dataset():
    # Arrange: a throwaway dataset name in every layer, removed afterwards with the writer's key
    name = f"contract_{uuid4().hex[:8]}"
    writer = _lake(Role.WRITER)

    yield name

    # Annihilate
    for layer in Layer:
        fs, root = open_location(writer._settings, layer)
        for path in (f"{root}/{name}", f"{root}/{name}.json"):
            if fs.exists(path):
                fs.rm(path, recursive=True)


@pytest.mark.parametrize("layer", list(Layer), ids=[layer.value for layer in Layer])
def test_writer_round_trips_partitions_and_pointers_in_every_layer(dataset, layer):
    # Arrange
    writer = _lake(Role.WRITER)

    # Act
    first = writer.replace_partition(layer, dataset, "p1", TABLE.to_batches(max_chunksize=100))
    again = writer.replace_partition(layer, dataset, "p1", [TABLE])
    writer.write_pointer(layer, f"{dataset}.json", {"version": "v1"})

    # Assert
    sizes = [batch.num_rows for batch in writer.iter_batches(layer, dataset, batch_size=100)]
    assert (first, again, writer.list_partitions(layer, dataset), sizes) == (250, 250, ["p1"], [100, 100, 50])
    assert writer.read_pointer(layer, f"{dataset}.json") == {"version": "v1"}


def test_reader_reads_what_the_writer_published_in_gold(dataset):
    # Arrange
    _lake(Role.WRITER).replace_partition(Layer.GOLD, dataset, "v1", [TABLE])

    # Act
    table = _lake(Role.READER).read_dataset(Layer.GOLD, dataset)

    # Assert
    assert table.num_rows == 250


# The analyst runs with the reader's key; the store, not our code, must stop it from changing
# gold or seeing the raw layers, so a bug or an injected prompt cannot get past it.
@pytest.mark.parametrize(
    "attempt",
    [
        lambda lake, name: lake.replace_partition(Layer.GOLD, name, "p2", [TABLE]),
        lambda lake, name: lake.write_pointer(Layer.GOLD, f"{name}.json", {"version": "forged"}),
        lambda lake, name: lake.list_partitions(Layer.BRONZE, name),
        lambda lake, name: lake.read_dataset(Layer.BRONZE, name, partitions=["p1"]),
        lambda lake, name: lake.read_dataset(Layer.SILVER, name),
    ],
    ids=["write_gold", "forge_gold_pointer", "list_bronze", "read_bronze", "read_silver"],
)
def test_reader_is_refused_everything_but_reading_gold(dataset, attempt):
    # Arrange
    writer = _lake(Role.WRITER)
    for layer in (Layer.BRONZE, Layer.SILVER):
        writer.replace_partition(layer, dataset, "p1", [TABLE])

    # Act / Assert
    with pytest.raises(PermissionError):
        attempt(_lake(Role.READER), dataset)
