from datetime import datetime
from typing import Any


def range_filter(minimum: float | datetime | None, maximum: float | datetime | None) -> dict[str, Any]:
    bounds: dict[str, Any] = {}
    if minimum is not None:
        bounds["$gte"] = minimum
    if maximum is not None:
        bounds["$lte"] = maximum
    return bounds
