import json
from datetime import UTC, datetime

import duckdb
import pytest

from app.analytics import gold
from app.analytics.gold import (
    GoldUnavailable,
    build_duckdb_secret,
    load_reader_settings,
    open_gold,
    parse_pointer,
)
from lake_config.settings import LakeSettings, Layer

URIS = {"LAKE_BRONZE_URI": "s3://lake-bronze", "LAKE_SILVER_URI": "s3://lake-silver", "LAKE_GOLD_URI": "s3://lake-gold"}
GARAGE = LakeSettings(
    layer_uris={Layer.GOLD: "s3://lake-gold"}, endpoint="http://127.0.0.1:3900", region="garage",
    addressing_style="path", key_id="GKreader", secret="s3cr3t",
)


def _pointer(**changes):
    raw = {"contract_version": 1, "version": "v=1", "data_as_of": "2026-10-21T13:00:00+00:00",
           "tables": {"dim_date": ["dim_date/v=1/all/part-00000.parquet"]}}
    return {**raw, **changes}


# The app reads gold with the analyst's key only: a bug or an injected prompt cannot write it.
def test_load_reader_settings_takes_the_reader_key_and_never_the_writer_key():
    # Arrange
    env = {**URIS, "LAKE_READER_KEY_ID": "GKreader", "LAKE_READER_SECRET": "r", "LAKE_WRITER_KEY_ID": "GKwriter", "LAKE_WRITER_SECRET": "w"}

    # Act
    settings = load_reader_settings(env)

    # Assert
    assert (settings.key_id, settings.secret, settings.layer_uris[Layer.GOLD]) == ("GKreader", "r", "s3://lake-gold")


@pytest.mark.parametrize(
    "env",
    [{}, {**URIS, "LAKE_READER_KEY_ID": "GKreader"}],
    ids=["nothing_set", "half_a_key"],
)
def test_load_reader_settings_incomplete_configuration_gives_none(env):
    # Arrange / Act
    settings = load_reader_settings(env)

    # Assert
    assert settings is None


@pytest.mark.parametrize(
    ("settings", "expected"),
    [
        (GARAGE, "CREATE OR REPLACE SECRET gold (TYPE s3, KEY_ID 'GKreader', SECRET 's3cr3t', REGION 'garage', "
                 "ENDPOINT '127.0.0.1:3900', USE_SSL false, URL_STYLE 'path')"),
        (LakeSettings(layer_uris={}, region="eu-central-1"), "CREATE OR REPLACE SECRET gold (TYPE s3, REGION 'eu-central-1')"),
        (LakeSettings(layer_uris={}, endpoint="https://s3.example.com", key_id="k'1", secret="s"),
         "CREATE OR REPLACE SECRET gold (TYPE s3, KEY_ID 'k''1', SECRET 's', ENDPOINT 's3.example.com', USE_SSL true)"),
    ],
    ids=["garage", "aws_with_role_credentials", "quote_in_a_value"],
)
def test_build_duckdb_secret_translates_the_shared_settings(settings, expected):
    # Arrange / Act
    statement = build_duckdb_secret(settings)

    # Assert
    assert statement == expected


def test_parse_pointer_resolves_files_under_the_root_and_reads_the_watermark():
    # Arrange / Act
    version = parse_pointer(_pointer(), "s3://lake-gold")

    # Assert
    assert version.version == "v=1"
    assert version.data_as_of == datetime(2026, 10, 21, 13, tzinfo=UTC)
    assert version.tables == {"dim_date": ("s3://lake-gold/dim_date/v=1/all/part-00000.parquet",)}


def test_parse_pointer_without_a_watermark_keeps_it_unknown():
    # Arrange / Act
    version = parse_pointer(_pointer(data_as_of=None), "s3://lake-gold")

    # Assert
    assert version.data_as_of is None


# A version the app does not know may have changed a unit or a meaning; guessing would be silent.
@pytest.mark.parametrize("contract", [None, 2, "1"], ids=["missing", "newer", "wrong_type"])
def test_parse_pointer_refuses_an_unknown_contract_version(contract):
    # Arrange / Act / Assert
    with pytest.raises(GoldUnavailable):
        parse_pointer(_pointer(contract_version=contract), "s3://lake-gold")


@pytest.fixture
def local_gold(tmp_path):
    # Arrange: a gold root on disk with one published table
    (tmp_path / "dim_date/v=1/all").mkdir(parents=True)
    duckdb.execute(f"COPY (SELECT 20261021 AS date_key) TO '{tmp_path}/dim_date/v=1/all/part-00000.parquet' (FORMAT parquet)")
    (tmp_path / "_current.json").write_text(json.dumps(_pointer()))
    return LakeSettings(layer_uris={Layer.GOLD: str(tmp_path)})


def test_open_gold_reads_the_pointer_and_the_files_it_names(local_gold):
    # Arrange / Act
    with open_gold(local_gold) as (connection, version):
        rows = connection.execute("SELECT date_key FROM read_parquet(?)", [list(version.tables["dim_date"])]).fetchall()

    # Assert
    assert (version.version, rows) == ("v=1", [(20261021,)])


@pytest.mark.parametrize(
    "settings",
    [None, LakeSettings(layer_uris={Layer.GOLD: "/nonexistent/gold"})],
    ids=["not_configured", "no_pointer"],
)
def test_open_gold_without_a_readable_pointer_is_unavailable(settings):
    # Arrange / Act / Assert
    with pytest.raises(GoldUnavailable):
        with open_gold(settings):
            pass


# Files a published version names can vanish (a reader slower than two publications); that is the
# store being unavailable, while a mistake in the SQL is a bug and must not hide behind it.
def test_open_gold_missing_data_file_is_unavailable_but_a_bad_query_is_not(local_gold, tmp_path):
    # Arrange
    (tmp_path / "dim_date/v=1/all/part-00000.parquet").unlink()

    # Act / Assert
    with pytest.raises(GoldUnavailable):
        with open_gold(local_gold) as (connection, version):
            connection.execute("SELECT * FROM read_parquet(?)", [list(version.tables["dim_date"])])
    with pytest.raises(duckdb.BinderException):
        with open_gold(local_gold) as (connection, version):
            connection.execute("SELECT no_such_column FROM range(1)")


class RecordingConnection:
    def __init__(self):
        self.statements = []

    def execute(self, statement, parameters=None):
        self.statements.append(statement)
        return self


def test_connect_to_s3_loads_httpfs_and_registers_the_reader_secret(monkeypatch):
    # Arrange
    connection = RecordingConnection()
    monkeypatch.setattr(gold.duckdb, "connect", lambda: connection)

    # Act
    gold.connect(GARAGE)

    # Assert
    assert connection.statements == ["INSTALL httpfs", "LOAD httpfs", build_duckdb_secret(GARAGE)]


def test_open_gold_failing_to_connect_is_unavailable(monkeypatch):
    # Arrange
    def refuse(settings):
        raise duckdb.IOException("Failed to download extension httpfs")

    monkeypatch.setattr(gold, "connect", refuse)

    # Act / Assert
    with pytest.raises(GoldUnavailable):
        with open_gold(GARAGE):
            pass
