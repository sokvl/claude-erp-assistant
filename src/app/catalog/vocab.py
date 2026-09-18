from collections.abc import Mapping
from typing import Any

VOCAB_FIELDS: Mapping[str, str] = {
    "category": "category",
    "brand": "brand",
    "architecture": "specs.architecture",
    "memory_type": "specs.memoryType",
    "use_case": "specs.useCases",
}


def get_all_vocabularies(collection: Any) -> dict[str, list[str]]:
    return {param: sorted(collection.distinct(path)) for param, path in VOCAB_FIELDS.items()}
