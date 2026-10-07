import os
from collections.abc import Mapping
from functools import cache
from pathlib import Path

import hvac

SECRET_PATH = "invoices-app"


@cache
def vault_client() -> hvac.Client | None:
    address = os.environ.get("VAULT_ADDR")
    if not address:
        return None
    client = hvac.Client(url=address, timeout=5)
    if token := os.environ.get("VAULT_TOKEN"):
        client.token = token
    else:
        client.auth.approle.login(role_id=_setting("VAULT_ROLE_ID"), secret_id=_setting("VAULT_SECRET_ID"))
    return client


def _setting(name: str) -> str:
    return os.environ.get(name) or Path(os.environ[f"{name}_FILE"]).read_text().strip()


@cache
def app_secrets() -> Mapping[str, str]:
    client = vault_client()
    if client is None:
        return {}
    response = client.secrets.kv.v2.read_secret_version(path=SECRET_PATH, raise_on_deleted_version=True)
    return response["data"]["data"]


def secret(name: str, default: str | None = None) -> str | None:
    return app_secrets().get(name) or os.environ.get(name) or default
