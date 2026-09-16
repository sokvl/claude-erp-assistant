import sys
from pathlib import Path

import pytest

from app.catalog import vocab

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "seed"))

from products import USE_CASE_TAGS  # noqa: E402

pytestmark = pytest.mark.integration


# Deriving the vocabulary from the data means a typo'd tag in the catalog
# silently becomes a valid query value. This is the check that catches it.
def test_seeded_use_case_tags_stay_within_the_controlled_vocabulary(mongo_client):
    # Arrange
    products = mongo_client["invoices_db"]["products"]

    # Act
    tags = set(products.distinct("specs.useCases"))

    # Assert
    assert tags <= set(USE_CASE_TAGS), f"unexpected tags: {tags - set(USE_CASE_TAGS)}"


@pytest.mark.parametrize(
    ("param", "expected"),
    [
        ("category", {"GPU", "CPU", "RAM", "Storage", "PSU", "Case", "Cooling",
                      "Networking", "Monitor", "Motherboard", "Accessory"}),
        ("architecture", {"Ada Lovelace", "Ampere", "CDNA 3", "Hopper", "RDNA 3"}),
        ("memory_type", {"GDDR6", "GDDR6 ECC", "GDDR6X", "HBM2e", "HBM3"}),
    ],
    ids=["category", "architecture", "memory_type"],
)
def test_live_vocabulary_matches_the_seeded_catalog(mongo_client, param, expected):
    # Arrange
    vocab.clear_cache()
    products = mongo_client["invoices_db"]["products"]

    # Act
    values = vocab.get_vocabulary(products, param)

    # Assert
    assert values == frozenset(expected)
    vocab.clear_cache()
