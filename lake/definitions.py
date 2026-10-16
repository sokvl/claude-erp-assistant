import os
from datetime import UTC, datetime

import dagster as dg
import pyarrow as pa
from pymongo import MongoClient

from lake.bronze import BRONZE_SCHEMA, DATASET, BronzeLoad, build_window, count_window, load_bronze, name_partition
from lake.settings import Layer, Role, load_settings
from lake.storage import Lake

hourly = dg.HourlyPartitionsDefinition(start_date=os.environ.get("LAKE_START", "2026-10-16-00:00"), timezone="UTC")

MATCHES_MONGO = "matches_mongo_count"
SCHEMA_IS_STABLE = "matches_bronze_schema"
NO_UNKNOWN_FIELDS = "no_unknown_fields"


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


defs = dg.Definitions(
    assets=[bronze_invoices],
    resources={"lake": LakeResource(), "mongo": MongoSource(uri=dg.EnvVar("LAKE_MONGO_URI"))},
)
