import json
from collections.abc import Iterable, Iterator, Sequence
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
from fsspec import AbstractFileSystem
from fsspec.core import url_to_fs

from lake.settings import LakeSettings, Layer

PART_FILE = "part-{:05d}.parquet"
DEFAULT_BATCH_ROWS = 50_000


def build_storage_options(settings: LakeSettings, uri: str) -> dict[str, Any]:
    if not uri.startswith("s3://"):
        return {}
    options: dict[str, Any] = {}
    if settings.endpoint:
        options["endpoint_url"] = settings.endpoint
    if settings.key_id:
        options["key"] = settings.key_id
        options["secret"] = settings.secret
    if settings.region:
        options["client_kwargs"] = {"region_name": settings.region}
    if settings.addressing_style:
        options["config_kwargs"] = {"s3": {"addressing_style": settings.addressing_style}}
    if settings.kms_key_id:
        options["s3_additional_kwargs"] = {"ServerSideEncryption": "aws:kms", "SSEKMSKeyId": settings.kms_key_id}
    return options


def open_location(settings: LakeSettings, layer: Layer) -> tuple[AbstractFileSystem, str]:
    uri = settings.layer_uris[layer]
    return url_to_fs(uri, **build_storage_options(settings, uri))


def write_parts(fs: AbstractFileSystem, directory: str, chunks: Iterable[pa.Table | pa.RecordBatch]) -> int:
    rows = 0
    non_empty = (chunk for chunk in chunks if chunk.num_rows)
    for index, chunk in enumerate(non_empty):
        table = chunk if isinstance(chunk, pa.Table) else pa.Table.from_batches([chunk])
        with fs.open(f"{directory}/{PART_FILE.format(index)}", "wb") as stream:
            pq.write_table(table, stream)
        rows += table.num_rows
    return rows


def stream_parts(
    fs: AbstractFileSystem, files: Iterable[str], batch_size: int, columns: Sequence[str] | None
) -> Iterator[pa.RecordBatch]:
    for file in files:
        with fs.open(file, "rb") as stream:
            yield from pq.ParquetFile(stream).iter_batches(batch_size=batch_size, columns=columns)


class Lake:
    def __init__(self, settings: LakeSettings) -> None:
        self._settings = settings
        self._locations: dict[Layer, tuple[AbstractFileSystem, str]] = {}

    def replace_partition(
        self, layer: Layer, dataset: str, partition: str, chunks: Iterable[pa.Table | pa.RecordBatch]
    ) -> int:
        fs, _ = self._resolve(layer)
        directory = self.build_partition_path(layer, dataset, partition)
        self._delete_if_present(fs, directory)
        return write_parts(fs, directory, chunks)

    def iter_batches(
        self,
        layer: Layer,
        dataset: str,
        partitions: Iterable[str] | None = None,
        batch_size: int = DEFAULT_BATCH_ROWS,
        columns: Sequence[str] | None = None,
    ) -> Iterator[pa.RecordBatch]:
        fs, _ = self._resolve(layer)
        files = self.list_part_files(layer, dataset, partitions)
        return stream_parts(fs, files, batch_size, columns)

    def read_dataset(
        self,
        layer: Layer,
        dataset: str,
        partitions: Iterable[str] | None = None,
        columns: Sequence[str] | None = None,
        schema: pa.Schema | None = None,
    ) -> pa.Table:
        batches = list(self.iter_batches(layer, dataset, partitions, columns=columns))
        if batches:
            return pa.Table.from_batches(batches)
        return schema.empty_table() if schema is not None else pa.table({})

    def list_partitions(self, layer: Layer, dataset: str) -> list[str]:
        fs, root = self._resolve(layer)
        base = f"{root}/{dataset}"
        if not fs.exists(base):
            return []
        return sorted(entry.rstrip("/").rsplit("/", 1)[-1] for entry in fs.ls(base, detail=False) if fs.isdir(entry))

    def list_part_files(self, layer: Layer, dataset: str, partitions: Iterable[str] | None = None) -> list[str]:
        fs, _ = self._resolve(layer)
        names = self.list_partitions(layer, dataset) if partitions is None else partitions
        return sorted(
            file for name in names for file in fs.glob(f"{self.build_partition_path(layer, dataset, name)}/*.parquet")
        )

    def write_pointer(self, layer: Layer, name: str, value: dict[str, Any]) -> None:
        fs, root = self._resolve(layer)
        with fs.open(f"{root}/{name}", "w") as stream:
            json.dump(value, stream)

    def read_pointer(self, layer: Layer, name: str) -> dict[str, Any] | None:
        fs, root = self._resolve(layer)
        path = f"{root}/{name}"
        if not fs.exists(path):
            return None
        with fs.open(path, "r") as stream:
            return json.load(stream)

    def build_partition_path(self, layer: Layer, dataset: str, partition: str) -> str:
        _, root = self._resolve(layer)
        return f"{root}/{dataset}/{partition}"

    def _resolve(self, layer: Layer) -> tuple[AbstractFileSystem, str]:
        if layer not in self._locations:
            self._locations[layer] = open_location(self._settings, layer)
        return self._locations[layer]

    @staticmethod
    def _delete_if_present(fs: AbstractFileSystem, path: str) -> None:
        if fs.exists(path):
            fs.rm(path, recursive=True)
