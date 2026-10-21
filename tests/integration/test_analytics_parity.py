from datetime import UTC, date, datetime
from uuid import uuid4

import pytest

from app.analytics.service import analyze_gold
from app.invoices.enums import GroupBy
from app.invoices.schemas import InvoiceAnalyticsParams
from app.invoices.service import analyze_invoices
from lake.bronze import DATASET as BRONZE_DATASET
from lake.bronze import to_table
from lake.gold import materialize_gold
from lake.silver import merge_silver
from lake.storage import Lake, open_location
from lake_config.settings import LakeSettings, Layer

pytestmark = pytest.mark.integration

AS_OF = date(2026, 6, 1)
PRODUCTS = {
    "GPU-A": ("A100", "NVIDIA", "GPU"),
    "LAP-D": ("Latitude", "Dell", "Laptop"),
    "LAP-H": ("EliteBook", "HP", "Laptop"),
    "SRV-D": ("PowerEdge", "Dell", "Server"),
}
CUSTOMERS = {"C1": "ALPHA co", "C2": "BETA llc", "C3": "GAMMA"}


def _invoice(key, customer, currency, posted, due, cleared, *lines):
    items = [
        {"lineNo": number, "sku": sku, "productName": PRODUCTS[sku][0], "brand": PRODUCTS[sku][1],
         "category": PRODUCTS[sku][2], "quantity": quantity, "unitPrice": price, "lineTotal": round(quantity * price, 2)}
        for number, (sku, quantity, price) in enumerate(lines, start=1)
    ]
    name = CUSTOMERS[customer]
    return {
        "_id": key, "invoiceId": key, "businessCode": "U001",
        "customer": {"number": customer, "name": name, "nameLower": name.lower()},
        "currency": currency, "documentType": "RV", "isOpen": cleared is None,
        "amounts": {"totalOpen": round(sum(item["lineTotal"] for item in items), 2)},
        "dates": {"postingDate": posted, "documentCreateDate": posted, "dueInDate": due, "baselineCreateDate": posted, "clearDate": cleared},
        "paymentTerms": "NAA8", "lines": items, "updatedAt": datetime(2026, 5, 31),
    }


# Every customer has one name and no invoice breaks a hard rule, so the intended differences
# (canonical labels, quarantine, staleness) cannot occur: any difference left is a bug. Every
# amount is a multiple of 8.40, and 840 cents divide by 1 to 8, so no average lands on half a
# cent: there MongoDB's $round on doubles is wrong (3000.495 -> 3000.49) while gold rounds the
# exact value half to even, which test_half_even_division_* checks against the right answer.
DOCUMENTS = [
    _invoice("I01", "C1", "USD", datetime(2025, 3, 10), datetime(2025, 3, 25), datetime(2025, 3, 20), ("LAP-D", 2, 504.00), ("GPU-A", 1, 1201.20)),
    _invoice("I02", "C1", "USD", datetime(2025, 3, 15), datetime(2025, 4, 14), None, ("LAP-H", 3, 336.00)),
    _invoice("I03", "C2", "USD", datetime(2025, 6, 1), datetime(2025, 6, 30), datetime(2025, 7, 15), ("SRV-D", 1, 3998.40)),
    _invoice("I04", "C2", "CAD", datetime(2025, 6, 2), datetime(2025, 7, 2), None, ("LAP-D", 1, 898.80), ("LAP-H", 1, 8.40)),
    _invoice("I05", "C3", "CAD", datetime(2025, 12, 31), datetime(2026, 1, 30), None, ("GPU-A", 2, 1503.60)),
    _invoice("I06", "C3", "USD", datetime(2026, 1, 1), datetime(2026, 1, 31), datetime(2026, 1, 10), ("LAP-D", 1, 16.80), ("LAP-H", 1, 25.20)),
    _invoice("I07", "C1", "USD", datetime(2026, 2, 14), datetime(2026, 3, 16), None, ("SRV-D", 2, 2503.20)),
    _invoice("I08", "C2", "USD", datetime(2026, 5, 20), datetime(2026, 6, 19), None, ("GPU-A", 1, 8.40)),
    _invoice("I09", "C3", "CAD", datetime(2026, 5, 31), datetime(2026, 5, 31), None, ("LAP-H", 1, 58.80)),
    _invoice("I10", "C1", "USD", datetime(2024, 11, 30), datetime(2024, 12, 30), datetime(2024, 12, 2), ("LAP-D", 1, 109.20)),
]
FILTERS = [
    {},
    {"currency": "USD"},
    {"status": "open"},
    {"status": "overdue"},
    {"status": "cleared"},
    {"posted_from": date(2025, 6, 1), "posted_to": date(2026, 1, 31)},
    {"customer": "beta"},
    {"customer": "C3"},
    {"min_amount": 100, "max_amount": 5000},
    {"invoice_id": "I04"},
    {"limit": 1},
]
CASES = [(group_by, filters) for group_by in [None, *GroupBy] for filters in FILTERS]


@pytest.fixture(scope="module")
def invoices(mongo_client):
    # Arrange: the documents in a throwaway MongoDB database
    name = f"test_parity_{uuid4().hex[:8]}"
    collection = mongo_client[name]["invoices"]
    collection.insert_many(DOCUMENTS)

    yield collection

    # Annihilate
    mongo_client.drop_database(name)


@pytest.fixture(scope="module")
def gold(tmp_path_factory):
    # Arrange: the same documents through the real pipeline (bronze, silver, gold), then the gold
    # layer copied to disk, where the app's reader finds it like it finds the bucket
    root = f"memory://parity-{uuid4().hex}"
    settings = LakeSettings(layer_uris={layer: f"{root}/{layer}" for layer in Layer})
    lake = Lake(settings)
    lake.replace_partition(Layer.BRONZE, BRONZE_DATASET, "changed_at=2026-05-31-00", [to_table(DOCUMENTS, datetime(2026, 5, 31, 1, tzinfo=UTC))])
    merge_silver(lake)
    materialize_gold(lake, datetime(2026, 6, 1, tzinfo=UTC), datetime(2026, 5, 31, 1, tzinfo=UTC))
    target = tmp_path_factory.mktemp("gold")
    fs, gold_root = open_location(settings, Layer.GOLD)
    for path in fs.find(gold_root):
        destination = target / path.removeprefix(f"{gold_root}/")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(fs.cat_file(path))
    return LakeSettings(layer_uris={Layer.GOLD: str(target)})


@pytest.mark.parametrize(("group_by", "filters"), CASES, ids=[f"{group_by or 'all'}-{'-'.join(f'{k}={v}' for k, v in filters.items()) or 'none'}" for group_by, filters in CASES])
def test_gold_answers_exactly_what_mongo_answers(invoices, gold, group_by, filters):
    # Arrange
    params = InvoiceAnalyticsParams(group_by=group_by, as_of=AS_OF, **filters)

    # Act
    expected = analyze_invoices(invoices, params)
    actual = analyze_gold(gold, params)

    # Assert
    assert actual.pop("dataAsOf") == "2026-05-31T01:00:00+00:00"
    assert actual == expected
