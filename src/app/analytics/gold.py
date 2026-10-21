import json
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import duckdb

from lake_config.settings import LakeConfigError, LakeSettings, Layer, Role, load_settings

CONTRACT_VERSION = 1
POINTER = "_current.json"


class GoldUnavailable(Exception):
    pass


@dataclass(frozen=True)
class GoldVersion:
    version: str
    data_as_of: datetime | None
    tables: Mapping[str, tuple[str, ...]]


def load_reader_settings(env: Mapping[str, str]) -> LakeSettings | None:
    try:
        return load_settings(env, Role.READER)
    except LakeConfigError:
        return None


def quote_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def build_duckdb_secret(settings: LakeSettings) -> str:
    options = ["TYPE s3"]
    if settings.key_id and settings.secret:
        options += [f"KEY_ID {quote_literal(settings.key_id)}", f"SECRET {quote_literal(settings.secret)}"]
    if settings.region:
        options.append(f"REGION {quote_literal(settings.region)}")
    if settings.endpoint:
        scheme, _, host = settings.endpoint.partition("://")
        options += [f"ENDPOINT {quote_literal(host)}", f"USE_SSL {str(scheme == 'https').lower()}"]
    if settings.addressing_style == "path":
        options.append("URL_STYLE 'path'")
    return f"CREATE OR REPLACE SECRET gold ({', '.join(options)})"


def parse_pointer(raw: Mapping[str, Any], root: str) -> GoldVersion:
    if raw.get("contract_version") != CONTRACT_VERSION:
        raise GoldUnavailable(f"gold contract version {raw.get('contract_version')!r} is not {CONTRACT_VERSION}")
    as_of = raw.get("data_as_of")
    return GoldVersion(
        version=raw["version"],
        data_as_of=datetime.fromisoformat(as_of) if as_of else None,
        tables={name: tuple(f"{root}/{file}" for file in files) for name, files in raw["tables"].items()},
    )


def connect(settings: LakeSettings) -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect()
    if settings.layer_uris[Layer.GOLD].startswith("s3://"):
        connection.execute("INSTALL httpfs")
        connection.execute("LOAD httpfs")
        connection.execute(build_duckdb_secret(settings))
    return connection


def read_version(connection: duckdb.DuckDBPyConnection, root: str) -> GoldVersion:
    path = f"{root}/{POINTER}"
    row = connection.execute("SELECT content FROM read_text(?)", [path]).fetchone()
    if row is None:
        raise GoldUnavailable(f"no gold pointer at {path}")
    return parse_pointer(json.loads(row[0]), root)


@contextmanager
def open_gold(settings: LakeSettings | None) -> Generator[tuple[duckdb.DuckDBPyConnection, GoldVersion]]:
    if settings is None:
        raise GoldUnavailable("gold is not configured: set the LAKE_*_URI and LAKE_READER_* variables")
    try:
        connection = connect(settings)
    except duckdb.IOException as exc:
        raise GoldUnavailable(f"cannot connect to gold: {exc}") from exc
    try:
        yield connection, read_version(connection, settings.layer_uris[Layer.GOLD])
    except duckdb.IOException as exc:
        raise GoldUnavailable(f"cannot read gold: {exc}") from exc
    finally:
        connection.close()
