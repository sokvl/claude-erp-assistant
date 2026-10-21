import os
from datetime import UTC, datetime

import dagster as dg
import pandas as pd
import pyarrow as pa
from pymongo import MongoClient

from lake.bronze import BRONZE_SCHEMA, DATASET, BronzeLoad, build_window, count_window, load_bronze, name_partition
from lake.gold import (
    build_gold,
    compare_with_silver,
    count_duplicate_keys,
    count_missing_keys,
    publish_gold,
    read_current,
    read_published_tables,
    read_silver_input,
)
from lake.reconciliation import Reconciliation, find_watermark, reconcile
from lake.settings import Layer, Role, load_settings
from lake.silver import (
    SilverRun,
    concatenate_frames,
    count_flagged,
    count_future_postings,
    find_duplicate_ids,
    find_schema_drift,
    merge_silver,
    read_invoice_facts,
    read_processed_partitions,
)
from lake.storage import Lake

FIRST_PARTITION = "2026-10-16-00:00"
FIRST_HOUR = datetime.strptime(FIRST_PARTITION, "%Y-%m-%d-%H:%M").replace(tzinfo=UTC)

hourly = dg.HourlyPartitionsDefinition(start_date=FIRST_PARTITION, timezone="UTC")

MATCHES_MONGO = "matches_mongo_count"
SCHEMA_IS_STABLE = "matches_bronze_schema"
NO_UNKNOWN_FIELDS = "no_unknown_fields"
UNIQUE_INVOICES = "unique_invoice_ids"
NO_FUTURE_POSTINGS = "no_future_postings"
SILVER_SCHEMAS = "matches_silver_schemas"
RECONCILED = "matches_mongo_per_month"
QUALITY_FLAGS = "few_quality_flags"
GOLD_UNIQUE_KEYS = "unique_keys"
GOLD_FOREIGN_KEYS = "foreign_keys_resolve"
GOLD_MATCHES_SILVER = "matches_silver_totals"


class LakeResource(dg.ConfigurableResource):
    role: str = Role.WRITER.value

    def open(self) -> Lake:
        return Lake(load_settings(os.environ, Role(self.role)))


class MongoSource(dg.ConfigurableResource):
    uri: str

    def connect(self) -> MongoClient:
        return MongoClient(self.uri)


def evaluate_checks(load: BronzeLoad, expected: int, schemas: list[pa.Schema]) -> list[dg.AssetCheckResult]:
    return [
        dg.AssetCheckResult(
            check_name=MATCHES_MONGO,
            passed=load.rows == expected,
            metadata={"bronze_rows": load.rows, "mongo_documents": expected},
        ),
        dg.AssetCheckResult(
            check_name=SCHEMA_IS_STABLE,
            passed=all(schema.equals(BRONZE_SCHEMA) for schema in schemas),
            metadata={"part_files": len(schemas)},
        ),
        dg.AssetCheckResult(
            check_name=NO_UNKNOWN_FIELDS,
            passed=not load.unknown_fields,
            severity=dg.AssetCheckSeverity.WARN,
            metadata={"unknown_fields": dg.MetadataValue.json(load.unknown_fields)},
        ),
    ]


@dg.asset(
    partitions_def=hourly,
    group_name="bronze",
    kinds={"mongodb", "parquet"},
    description="Invoices whose updatedAt falls in the hour, copied unchanged from MongoDB. The first partition holds the whole history.",
    check_specs=[
        dg.AssetCheckSpec(MATCHES_MONGO, asset="bronze_invoices", description="Rows equal the MongoDB documents in the same window."),
        dg.AssetCheckSpec(SCHEMA_IS_STABLE, asset="bronze_invoices", description="Every part file has the bronze schema."),
        dg.AssetCheckSpec(NO_UNKNOWN_FIELDS, asset="bronze_invoices", description="No source field is missing from the schema."),
    ],
)
def bronze_invoices(context: dg.AssetExecutionContext, lake: LakeResource, mongo: MongoSource) -> dg.MaterializeResult:
    span = context.partition_time_window
    window = build_window(span.start, span.end, first=context.partition_key == hourly.get_first_partition_key())
    partition = name_partition(span.start)
    store = lake.open()
    with mongo.connect() as client:
        invoices = client.get_default_database()["invoices"]
        load = load_bronze(store, invoices, window, partition, datetime.now(UTC))
        expected = count_window(invoices, window)
    schemas = store.read_part_schemas(Layer.BRONZE, DATASET, [partition])
    return dg.MaterializeResult(
        metadata={
            "rows": load.rows,
            "part_files": len(schemas),
            "path": store.build_partition_path(Layer.BRONZE, DATASET, partition),
            "window_since": window.since.isoformat() if window.since else "unbounded",
            "window_until": window.until.isoformat(),
        },
        check_results=evaluate_checks(load, expected, schemas),
    )


def evaluate_silver_checks(
    store: Lake, accepted: pd.DataFrame, facts: pd.DataFrame, reconciliation: Reconciliation
) -> list[dg.AssetCheckResult]:
    duplicates = find_duplicate_ids(facts["invoice_id"])
    future = count_future_postings(facts["posting_date"], pd.Timestamp.now(tz="UTC"))
    drift = find_schema_drift(store)
    flagged = count_flagged(accepted["quality_flags"])
    return [
        dg.AssetCheckResult(
            check_name=UNIQUE_INVOICES,
            passed=not duplicates,
            metadata={"duplicates": len(duplicates), "examples": dg.MetadataValue.json(duplicates[:20])},
        ),
        dg.AssetCheckResult(check_name=NO_FUTURE_POSTINGS, passed=future == 0, metadata={"future_postings": future}),
        dg.AssetCheckResult(check_name=SILVER_SCHEMAS, passed=not drift, metadata={"drifted": dg.MetadataValue.json(drift)}),
        dg.AssetCheckResult(
            check_name=RECONCILED,
            passed=reconciliation.watermark is not None and reconciliation.differences.empty,
            metadata={
                "watermark": reconciliation.watermark.isoformat() if reconciliation.watermark else "first hour not merged",
                "excluded_after_watermark": len(reconciliation.excluded),
                "months_differing": len(reconciliation.differences),
                "differences": dg.MetadataValue.md(reconciliation.differences.to_markdown(index=False))
                if not reconciliation.differences.empty
                else "none",
            },
        ),
        dg.AssetCheckResult(
            check_name=QUALITY_FLAGS,
            passed=flagged == 0,
            severity=dg.AssetCheckSeverity.WARN,
            metadata={"flagged_invoices": flagged, "accepted_invoices": len(accepted)},
        ),
    ]


def describe_run(run: SilverRun) -> dict:
    return {
        "bronze_partitions": dg.MetadataValue.json(run.bronze_partitions),
        "months_rewritten": len(run.months),
        "accepted_in_rewritten_months": run.invoices,
        "rejected_in_rewritten_months": run.rejected,
        "customers": run.customers,
    }


@dg.asset(
    deps=[bronze_invoices],
    group_name="silver",
    kinds={"pandas", "parquet"},
    description="One latest, validated version of every invoice, in posting-month partitions, with quarantine, lines and customers.",
    check_specs=[
        dg.AssetCheckSpec(UNIQUE_INVOICES, asset="silver_invoices", description="Every invoice id appears once across months and quarantine."),
        dg.AssetCheckSpec(NO_FUTURE_POSTINGS, asset="silver_invoices", description="No posting date lies in the future."),
        dg.AssetCheckSpec(SILVER_SCHEMAS, asset="silver_invoices", description="Every part file has its dataset's schema."),
        dg.AssetCheckSpec(RECONCILED, asset="silver_invoices", description="Per-month count, cents and open invoices equal MongoDB, leaving out invoices changed after the watermark."),
        dg.AssetCheckSpec(QUALITY_FLAGS, asset="silver_invoices", description="How many accepted invoices carry a soft-rule flag."),
    ],
)
def silver_invoices(lake: LakeResource, mongo: MongoSource) -> dg.MaterializeResult:
    store = lake.open()
    run = merge_silver(store)
    accepted, rejected = read_invoice_facts(store)
    facts = concatenate_frames([accepted, rejected])
    with mongo.connect() as client:
        reconciliation = reconcile(store, client.get_default_database()["invoices"], facts, FIRST_HOUR)
    return dg.MaterializeResult(
        metadata=describe_run(run),
        check_results=evaluate_silver_checks(store, accepted, facts, reconciliation),
    )


def evaluate_gold_checks(
    duplicates: dict[str, int], missing: dict[str, int], differences: pd.DataFrame
) -> list[dg.AssetCheckResult]:
    return [
        dg.AssetCheckResult(check_name=GOLD_UNIQUE_KEYS, passed=not duplicates, metadata={"duplicates": dg.MetadataValue.json(duplicates)}),
        dg.AssetCheckResult(check_name=GOLD_FOREIGN_KEYS, passed=not missing, metadata={"missing": dg.MetadataValue.json(missing)}),
        dg.AssetCheckResult(
            check_name=GOLD_MATCHES_SILVER,
            passed=differences.empty,
            metadata={"differences": dg.MetadataValue.md(differences.to_markdown(index=False)) if not differences.empty else "none"},
        ),
    ]


@dg.asset(
    deps=[silver_invoices],
    group_name="gold",
    kinds={"pandas", "parquet"},
    description="Star schema rebuilt from silver on every run and published behind gold/_current.json; the last three versions are kept.",
    check_specs=[
        dg.AssetCheckSpec(GOLD_UNIQUE_KEYS, asset="gold_invoices", description="No table repeats its key, so no join can fan out."),
        dg.AssetCheckSpec(GOLD_FOREIGN_KEYS, asset="gold_invoices", description="Every fact key has a row in its dimension."),
        dg.AssetCheckSpec(GOLD_MATCHES_SILVER, asset="gold_invoices", description="Invoices and lines per currency, count and cents, equal the accepted silver they were built from."),
    ],
)
def gold_invoices(lake: LakeResource) -> dg.MaterializeResult:
    store = lake.open()
    silver = read_silver_input(store)
    data_as_of = find_watermark(read_processed_partitions(store), FIRST_HOUR)
    run = publish_gold(store, build_gold(silver), datetime.now(UTC), data_as_of)
    published = read_published_tables(store, read_current(store))
    return dg.MaterializeResult(
        metadata={"version": run.version, "data_as_of": data_as_of.isoformat() if data_as_of else "unknown", "rows": dg.MetadataValue.json(run.rows), "removed_versions": len(run.removed)},
        check_results=evaluate_gold_checks(
            count_duplicate_keys(published), count_missing_keys(published), compare_with_silver(silver, published)
        ),
    )


defs = dg.Definitions(
    assets=[bronze_invoices, silver_invoices, gold_invoices],
    resources={"lake": LakeResource(), "mongo": MongoSource(uri=dg.EnvVar("LAKE_MONGO_URI"))},
)
