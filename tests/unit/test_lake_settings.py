import pytest

from lake.settings import LakeConfigError, Layer, Role, load_settings

URIS = {
    "LAKE_BRONZE_URI": "s3://lake-bronze",
    "LAKE_SILVER_URI": "s3://lake-silver",
    "LAKE_GOLD_URI": "s3://lake-gold",
}
GARAGE = {
    **URIS,
    "LAKE_S3_ENDPOINT": "http://127.0.0.1:3900",
    "LAKE_S3_REGION": "garage",
    "LAKE_S3_ADDRESSING_STYLE": "path",
    "LAKE_WRITER_KEY_ID": "GKwriter",
    "LAKE_WRITER_SECRET": "writer-secret",
    "LAKE_READER_KEY_ID": "GKreader",
    "LAKE_READER_SECRET": "reader-secret",
}


def test_load_settings_garage_env_fills_every_field():
    # Arrange / Act
    settings = load_settings(GARAGE, Role.WRITER)

    # Assert
    assert settings.layer_uris == {Layer.BRONZE: "s3://lake-bronze", Layer.SILVER: "s3://lake-silver", Layer.GOLD: "s3://lake-gold"}
    assert (settings.endpoint, settings.region, settings.addressing_style) == ("http://127.0.0.1:3900", "garage", "path")
    assert (settings.key_id, settings.secret, settings.kms_key_id) == ("GKwriter", "writer-secret", None)


@pytest.mark.parametrize(
    ("role", "expected"),
    [(Role.WRITER, ("GKwriter", "writer-secret")), (Role.READER, ("GKreader", "reader-secret"))],
    ids=["writer", "reader"],
)
def test_load_settings_role_picks_its_own_keys(role, expected):
    # Arrange / Act
    settings = load_settings(GARAGE, role)

    # Assert
    assert (settings.key_id, settings.secret) == expected


# On AWS the code runs under an IAM role: no endpoint and no keys means s3fs falls back to
# the default endpoint and the default credential chain.
def test_load_settings_aws_env_leaves_endpoint_and_keys_empty():
    # Arrange
    env = {**URIS, "LAKE_S3_ENDPOINT": "", "LAKE_S3_REGION": "eu-central-1", "LAKE_WRITER_KEY_ID": ""}

    # Act
    settings = load_settings(env, Role.WRITER)

    # Assert
    assert (settings.endpoint, settings.key_id, settings.secret, settings.region) == (None, None, None, "eu-central-1")


def test_load_settings_trailing_slash_is_dropped_from_layer_uris():
    # Arrange
    env = {**URIS, "LAKE_GOLD_URI": "s3://acme-lake/gold/"}

    # Act
    settings = load_settings(env, Role.READER)

    # Assert
    assert settings.layer_uris[Layer.GOLD] == "s3://acme-lake/gold"


@pytest.mark.parametrize(
    ("missing", "message"),
    [
        (["LAKE_GOLD_URI"], "set LAKE_GOLD_URI"),
        (list(URIS), "set LAKE_BRONZE_URI, LAKE_SILVER_URI, LAKE_GOLD_URI"),
    ],
    ids=["one_layer", "every_layer"],
)
def test_load_settings_missing_layer_uri_names_the_variable(missing, message):
    # Arrange
    env = {name: value for name, value in GARAGE.items() if name not in missing}

    # Act / Assert
    with pytest.raises(LakeConfigError, match=message):
        load_settings(env, Role.WRITER)


@pytest.mark.parametrize(
    "dropped",
    ["LAKE_WRITER_KEY_ID", "LAKE_WRITER_SECRET"],
    ids=["secret_without_id", "id_without_secret"],
)
def test_load_settings_half_a_key_pair_is_rejected(dropped):
    # Arrange
    env = {name: value for name, value in GARAGE.items() if name != dropped}

    # Act / Assert
    with pytest.raises(LakeConfigError, match="set both LAKE_WRITER_KEY_ID and LAKE_WRITER_SECRET"):
        load_settings(env, Role.WRITER)
