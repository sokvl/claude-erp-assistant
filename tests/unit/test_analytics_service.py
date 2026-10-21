from datetime import UTC, date, datetime
from uuid import uuid4

import pytest

from app.analytics.gold import GoldUnavailable
from app.analytics.service import analyze_gold, format_date_key
from app.invoices.enums import GroupBy
from app.invoices.schemas import InvoiceAnalyticsParams
from lake.bronze import DATASET as BRONZE_DATASET
from lake.bronze import to_table
from lake.gold import materialize_gold
from lake.silver import merge_silver
from lake.storage import Lake, open_location
from lake_config.settings import LakeSettings, Layer

AS_OF = date(2026, 10, 21)


def _invoice(key, number, name, amount, posted, lines, cleared=None):
    return {
        "_id": key, "customer": {"number": number, "name": name, "nameLower": name.lower()}, "currency": "USD",
        "isOpen": cleared is None, "amounts": {"totalOpen": amount},
        "dates": {"postingDate": posted, "dueInDate": datetime(2026, 9, 30), "clearDate": cleared},
        "lines": [{"lineNo": n, "sku": sku, "productName": product, "brand": brand, "category": "Laptop",
                   "quantity": quantity, "unitPrice": total / quantity, "lineTotal": total}
                  for n, (sku, product, brand, quantity, total) in enumerate(lines, start=1)],
        "updatedAt": datetime(2026, 10, 20),
    }


@pytest.fixture(scope="module")
def gold(tmp_path_factory):
    # Arrange: gold built by the pipeline's own code, then read by the app's code: the contract test
    documents = [
        _invoice("S1", "C1", "DOLLAR llc", 100.00, datetime(2026, 9, 1), [("LAP-D", "Latitude", "Dell", 2, 60.00), ("NB-H", "EliteBook", "HP", 1, 40.00)]),
        _invoice("S2", "C1", "DOLLAR corp", 50.00, datetime(2026, 9, 2), [("LAP-D", "Latitude", "Dell", 1, 50.00)], cleared=datetime(2026, 9, 11)),
    ]
    root = f"memory://analytics-{uuid4().hex}"
    settings = LakeSettings(layer_uris={layer: f"{root}/{layer}" for layer in Layer})
    lake = Lake(settings)
    lake.replace_partition(Layer.BRONZE, BRONZE_DATASET, "changed_at=2026-10-20-00", [to_table(documents, datetime(2026, 10, 20, 1, tzinfo=UTC))])
    merge_silver(lake)
    materialize_gold(lake, datetime(2026, 10, 21, tzinfo=UTC), datetime(2026, 10, 20, 1, tzinfo=UTC))
    target = tmp_path_factory.mktemp("gold")
    fs, gold_root = open_location(settings, Layer.GOLD)
    for path in fs.find(gold_root):
        destination = target / path.removeprefix(f"{gold_root}/")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(fs.cat_file(path))
    return LakeSettings(layer_uris={Layer.GOLD: str(target)})


def test_analyze_gold_without_grouping_has_the_mongo_shape_plus_the_watermark(gold):
    # Arrange / Act
    result = analyze_gold(gold, InvoiceAnalyticsParams(as_of=AS_OF, currency="USD"))

    # Assert
    assert result == {
        "asOf": "2026-10-21",
        "dataAsOf": "2026-10-20T01:00:00+00:00",
        "groupBy": None,
        "filters": {"currency": "USD"},
        "coverage": {"firstPostingDate": "2026-09-01", "lastPostingDate": "2026-09-02"},
        "currencies": [{"currency": "USD", "groupCount": 1, "rows": [{
            "invoiceCount": 2, "totalAmount": 150.0, "averageAmount": 75.0, "openAmount": 100.0,
            "overdueAmount": 100.0, "averageDaysToPay": 9.0,
        }]}],
    }


# Known values, not only column names: a silent change of unit or meaning in gold (cents instead
# of dollars, working days instead of calendar days) shows up here, not in a manager's report.
@pytest.mark.parametrize(
    ("group_by", "expected"),
    [
        (GroupBy.CUSTOMER, [{"key": "C1", "label": "DOLLAR", "invoiceCount": 2, "totalAmount": 150.0}]),
        (GroupBy.BRAND, [{"key": "Dell", "invoiceCount": 2, "totalAmount": 110.0, "units": 3},
                         {"key": "HP", "invoiceCount": 1, "totalAmount": 40.0, "units": 1}]),
        (GroupBy.PRODUCT, [{"key": "LAP-D", "label": "Latitude", "totalAmount": 110.0, "units": 3, "averageUnitPrice": 36.67},
                           {"key": "NB-H", "label": "EliteBook", "totalAmount": 40.0, "units": 1, "averageUnitPrice": 40.0}]),
        (GroupBy.MONTH, [{"key": "2026-09-01", "invoiceCount": 2, "totalAmount": 150.0}]),
    ],
    ids=["customer_with_canonical_label", "brand_with_units", "product_with_unit_price", "month"],
)
def test_analyze_gold_rows_carry_the_fields_of_their_grouping(gold, group_by, expected):
    # Arrange / Act
    rows = analyze_gold(gold, InvoiceAnalyticsParams(as_of=AS_OF, group_by=group_by))["currencies"][0]["rows"]

    # Assert
    assert [{field: row[field] for field in want} for row, want in zip(rows, expected)] == expected
    assert len(rows) == len(expected)
    assert ("label" in rows[0]) == (group_by in (GroupBy.CUSTOMER, GroupBy.PRODUCT))
    assert ("units" in rows[0]) == (group_by in (GroupBy.BRAND, GroupBy.PRODUCT))


def test_analyze_gold_customer_found_by_another_name_it_was_invoiced_under(gold):
    # Arrange / Act
    result = analyze_gold(gold, InvoiceAnalyticsParams(as_of=AS_OF, customer="dollar corp"))

    # Assert
    assert result["currencies"][0]["rows"][0]["invoiceCount"] == 2


def test_analyze_gold_without_configuration_is_unavailable():
    # Arrange / Act / Assert
    with pytest.raises(GoldUnavailable):
        analyze_gold(None, InvoiceAnalyticsParams(as_of=AS_OF))


@pytest.mark.parametrize(("key", "expected"), [(20260901, "2026-09-01"), (None, None)], ids=["date", "no_data"])
def test_format_date_key_reads_yyyymmdd(key, expected):
    # Arrange / Act / Assert
    assert format_date_key(key) == expected
