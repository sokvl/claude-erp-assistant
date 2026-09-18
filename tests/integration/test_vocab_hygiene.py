import pytest

from app.catalog import vocab
from app.catalog.enums import Architecture, Brand, Category, MemoryType, UseCase

pytestmark = pytest.mark.integration

ENUMS = {
    "category": Category,
    "brand": Brand,
    "architecture": Architecture,
    "memory_type": MemoryType,
    "use_case": UseCase,
}


# test_seed_catalog checks the code; this checks the database the app actually
# serves. A stored value outside the enums is a product no search can reach.
@pytest.mark.parametrize("param", list(ENUMS), ids=list(ENUMS))
def test_live_catalog_values_are_all_searchable_enum_values(mongo_client, param):
    # Arrange
    products = mongo_client["invoices_db"]["products"]

    # Act
    values = set(vocab.get_all_vocabularies(products)[param])

    # Assert
    assert values <= {member.value for member in ENUMS[param]}, f"unsearchable: {values - set(ENUMS[param])}"
