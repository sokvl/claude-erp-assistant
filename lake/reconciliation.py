from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from lake.bronze import name_partition, read_source
from lake.silver import read_processed_partitions
from lake.storage import Lake

TIMEOUT_MS = 60_000
HOUR = timedelta(hours=1)
MONTH = "posting_month"
TOTALS = ["invoices", "amount_cents", "open_invoices"]


@dataclass(frozen=True)
class Reconciliation:
    watermark: datetime | None
    excluded: list[str]
    differences: pd.DataFrame


def find_watermark(processed: Iterable[str], first_hour: datetime) -> datetime | None:
    done = set(processed)
    hour = first_hour
    while name_partition(hour) in done:
        hour += HOUR
    return hour if hour > first_hour else None


def build_changed_filter(watermark: datetime) -> dict[str, Any]:
    return {"updatedAt": {"$gte": watermark}}


def build_month_totals_pipeline(excluded: list[str]) -> list[dict[str, Any]]:
    return [
        {"$match": {"_id": {"$nin": excluded}}},
        {
            "$group": {
                "_id": {"$dateToString": {"format": "%Y-%m", "date": "$dates.postingDate"}},
                "invoices": {"$sum": 1},
                "amount_cents": {"$sum": {"$round": [{"$multiply": ["$amounts.totalOpen", 100]}, 0]}},
                "open_invoices": {"$sum": {"$cond": ["$isOpen", 1, 0]}},
            }
        },
        {"$sort": {"_id": 1}},
    ]


def find_changed_ids(collection: Any, watermark: datetime) -> list[str]:
    return sorted(read_source(collection).distinct("_id", build_changed_filter(watermark), maxTimeMS=TIMEOUT_MS))


def read_mongo_totals(collection: Any, excluded: list[str]) -> pd.DataFrame:
    rows = read_source(collection).aggregate(build_month_totals_pipeline(excluded), maxTimeMS=TIMEOUT_MS)
    totals = pd.DataFrame([{MONTH: row["_id"], **{name: row[name] for name in TOTALS}} for row in rows], columns=[MONTH, *TOTALS])
    return totals.astype({name: "int64" for name in TOTALS})


def summarize_silver(facts: pd.DataFrame, excluded: list[str]) -> pd.DataFrame:
    kept = facts[~facts["invoice_id"].isin(excluded)]
    measures = pd.DataFrame(
        {
            MONTH: kept[MONTH],
            "invoices": 1,
            "amount_cents": (kept["amount"].fillna(0) * 100).round().astype("int64"),
            "open_invoices": kept["is_open"].fillna(False).astype(bool).astype("int64"),
        }
    )
    return measures.groupby(MONTH, dropna=False, as_index=False)[TOTALS].sum().sort_values(MONTH).reset_index(drop=True)


def compare_totals(silver: pd.DataFrame, mongo: pd.DataFrame) -> pd.DataFrame:
    both = silver.merge(mongo, on=MONTH, how="outer", suffixes=("_silver", "_mongo"))
    both = both.fillna({f"{name}_{side}": 0 for name in TOTALS for side in ("silver", "mongo")})
    differs = pd.concat([both[f"{name}_silver"] != both[f"{name}_mongo"] for name in TOTALS], axis=1).any(axis=1)
    return both[differs].reset_index(drop=True)


def reconcile(lake: Lake, invoices: Any, facts: pd.DataFrame, first_hour: datetime) -> Reconciliation:
    watermark = find_watermark(read_processed_partitions(lake), first_hour)
    if watermark is None:
        return Reconciliation(watermark=None, excluded=[], differences=pd.DataFrame())
    excluded = find_changed_ids(invoices, watermark)
    differences = compare_totals(summarize_silver(facts, excluded), read_mongo_totals(invoices, excluded))
    return Reconciliation(watermark=watermark, excluded=excluded, differences=differences)
