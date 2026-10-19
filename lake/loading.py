from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import TypeVar

import pyarrow as pa

from lake.settings import Layer
from lake.storage import Lake

Batch = TypeVar("Batch")


@dataclass(frozen=True)
class Target:
    layer: Layer
    dataset: str
    partition: str


def load_partition(
    lake: Lake, target: Target, batches: Iterable[Batch], transform: Callable[[Batch], pa.Table | pa.RecordBatch]
) -> int:
    tables = (transform(batch) for batch in batches)
    return lake.replace_partition(target.layer, target.dataset, target.partition, tables)
