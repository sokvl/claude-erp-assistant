import time
from collections.abc import Mapping
from typing import Any

# Query param -> document path. Vocabularies come from the data, not a static
# enum, so adding a product can never make its own values unsearchable.
VOCAB_FIELDS: Mapping[str, str] = {
    "category": "category",
    "brand": "brand",
    "architecture": "specs.architecture",
    "memory_type": "specs.memoryType",
    "use_case": "specs.useCases",
}

TTL_SECONDS = 300

_cache: dict[str, tuple[frozenset[str], float]] = {}


def get_vocabulary(collection: Any, param: str) -> frozenset[str]:
    """Allowed values for a filter param, cached - advanced search is expected to be hot."""
    if param not in VOCAB_FIELDS:
        raise KeyError(f"{param!r} is not a vocabulary field")

    cached = _cache.get(param)
    now = time.monotonic()
    if cached is not None and cached[1] > now:
        return cached[0]

    # distinct() drops None, so non-GPU products contribute nothing to spec
    # vocabularies. It also flattens arrays, which is what we want for useCases.
    values = frozenset(collection.distinct(VOCAB_FIELDS[param]))
    _cache[param] = (values, now + TTL_SECONDS)
    return values


def get_all_vocabularies(collection: Any) -> dict[str, list[str]]:
    return {param: sorted(get_vocabulary(collection, param)) for param in VOCAB_FIELDS}


def clear_cache() -> None:
    _cache.clear()
