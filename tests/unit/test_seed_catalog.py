import sys
from pathlib import Path

import pytest

from app.catalog.enums import Architecture, Brand, Category, MemoryType, UseCase

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "seed"))

from products import PRODUCTS  # noqa: E402

GPUS = [product for product in PRODUCTS if "specs" in product]


# The enums are the only values a search accepts, so a seeded value outside
# them is a product nobody can filter for, and an enum value with no product
# is a filter the model is offered that can never match.
@pytest.mark.parametrize(
    ("enum", "seeded"),
    [
        (Category, [product["category"] for product in PRODUCTS]),
        (Brand, [product["brand"] for product in PRODUCTS]),
        (Architecture, [gpu["specs"]["architecture"] for gpu in GPUS]),
        (MemoryType, [gpu["specs"]["memoryType"] for gpu in GPUS]),
        (UseCase, [tag for gpu in GPUS for tag in gpu["specs"]["useCases"]]),
    ],
    ids=["category", "brand", "architecture", "memory_type", "use_case"],
)
def test_seeded_catalog_uses_exactly_the_enum_values(enum, seeded):
    # Arrange / Act / Assert
    assert set(seeded) == {member.value for member in enum}
