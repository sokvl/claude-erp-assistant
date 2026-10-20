from datetime import datetime
from uuid import uuid4

import pandas as pd
import pytest

from lake.bronze import to_table
from lake.reconciliation import TOTALS, build_changed_filter, build_month_totals_pipeline, summarize_silver
from lake.silver import flatten_invoices, name_month

pytestmark = pytest.mark.integration

W = datetime(2026, 10, 19, 6)


def _invoice(key, amount, posted, is_open=True, updated=datetime(2026, 10, 15, 14, 42)):
    return {
        "_id": key, "isOpen": is_open, "currency": "USD",
        "customer": {"number": "0200769623", "name": "GENE in", "nameLower": "gene in"},
        "amounts": {"totalOpen": amount}, "dates": {"postingDate": posted}, "updatedAt": updated,
    }


# Month boundaries in UTC, float amounts whose cents round differently when summed first, a closed
# invoice and one changed after the watermark.
DOCUMENTS = [
    _invoice("S1", 54273.28, datetime(2026, 9, 30, 23, 30)),
    _invoice("S2", 0.1, datetime(2026, 9, 1)),
    _invoice("S3", 0.2, datetime(2026, 9, 2), is_open=False),
    _invoice("S4", 19.99, datetime(2026, 10, 1, 0, 0)),
    _invoice("S5", 10.0, datetime(2026, 10, 2), updated=datetime(2026, 10, 19, 6, 51)),
]


@pytest.fixture
def invoices(mongo_client):
    # Arrange: a throwaway database with the five invoices
    name = f"test_reconciliation_{uuid4().hex[:8]}"
    collection = mongo_client[name]["invoices"]
    collection.insert_many(DOCUMENTS)

    yield collection

    # Annihilate
    mongo_client.drop_database(name)


# The check is only trustworthy if Mongo and pandas compute the same numbers from the same
# documents; any drift here would be a false alarm every hour.
def test_month_totals_pipeline_matches_the_silver_summary_of_the_same_invoices(invoices):
    # Arrange
    excluded = sorted(invoices.distinct("_id", build_changed_filter(W)))
    facts = flatten_invoices(to_table(DOCUMENTS, datetime(2026, 10, 19, 7)))
    facts["posting_month"] = name_month(facts["posting_date"])

    # Act
    rows = list(invoices.aggregate(build_month_totals_pipeline(excluded)))

    # Assert
    mongo = pd.DataFrame([{"posting_month": row["_id"], **{name: int(row[name]) for name in TOTALS}} for row in rows])
    assert excluded == ["S5"]
    assert mongo.to_dict("records") == summarize_silver(facts, excluded).to_dict("records")
    assert mongo.to_dict("records") == [
        {"posting_month": "2026-09", "invoices": 3, "amount_cents": 5427358, "open_invoices": 2},
        {"posting_month": "2026-10", "invoices": 1, "amount_cents": 1999, "open_invoices": 1},
    ]
