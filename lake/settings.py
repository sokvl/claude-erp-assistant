from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum


class Layer(StrEnum):
    BRONZE = "bronze"
    SILVER = "silver"
    GOLD = "gold"


class Role(StrEnum):
    WRITER = "writer"
    READER = "reader"


class LakeConfigError(ValueError):
    pass


@dataclass(frozen=True)
class LakeSettings:
    layer_uris: Mapping[Layer, str]
    endpoint: str | None = None
    region: str | None = None
    addressing_style: str | None = None
    key_id: str | None = None
    secret: str | None = None
    kms_key_id: str | None = None


def load_settings(env: Mapping[str, str], role: Role) -> LakeSettings:
    key_id, secret = read_credentials(env, role)
    return LakeSettings(
        layer_uris=read_layer_uris(env),
        endpoint=read_optional(env, "LAKE_S3_ENDPOINT"),
        region=read_optional(env, "LAKE_S3_REGION"),
        addressing_style=read_optional(env, "LAKE_S3_ADDRESSING_STYLE"),
        key_id=key_id,
        secret=secret,
        kms_key_id=read_optional(env, "LAKE_S3_KMS_KEY_ID"),
    )


def read_layer_uris(env: Mapping[str, str]) -> dict[Layer, str]:
    names = {layer: f"LAKE_{layer.upper()}_URI" for layer in Layer}
    missing = [name for name in names.values() if not env.get(name)]
    if missing:
        raise LakeConfigError(f"set {', '.join(missing)}")
    return {layer: env[name].rstrip("/") for layer, name in names.items()}


def read_credentials(env: Mapping[str, str], role: Role) -> tuple[str | None, str | None]:
    id_name, secret_name = f"LAKE_{role.upper()}_KEY_ID", f"LAKE_{role.upper()}_SECRET"
    key_id, secret = read_optional(env, id_name), read_optional(env, secret_name)
    if (key_id is None) != (secret is None):
        raise LakeConfigError(f"set both {id_name} and {secret_name}, or neither")
    return key_id, secret


def read_optional(env: Mapping[str, str], name: str) -> str | None:
    return env.get(name) or None
