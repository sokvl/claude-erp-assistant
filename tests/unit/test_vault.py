import pytest

from app import vault
from app.vault import app_secrets, secret, vault_client

STORED = {"ANTHROPIC_API_KEY": "sk-from-vault", "MONGO_URI": "mongodb://app:pw@mongo:27017"}


class FakeKv:
    def __init__(self, client):
        self.client = client

    def read_secret_version(self, path, raise_on_deleted_version):
        self.client.reads.append(path)
        return {"data": {"data": STORED}}


class FakeAppRole:
    def __init__(self, client):
        self.client = client

    def login(self, role_id, secret_id):
        self.client.logins.append((role_id, secret_id))
        self.client.token = "approle-token"


class FakeClient:
    def __init__(self, url, timeout):
        self.url = url
        self.token = None
        self.logins = []
        self.reads = []
        self.secrets = type("Secrets", (), {"kv": type("Kv", (), {"v2": FakeKv(self)})()})()
        self.auth = type("Auth", (), {"approle": FakeAppRole(self)})()


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    for name in ("VAULT_ADDR", "VAULT_TOKEN", "VAULT_ROLE_ID", "VAULT_ROLE_ID_FILE", "VAULT_SECRET_ID",
                 "VAULT_SECRET_ID_FILE", "ANTHROPIC_API_KEY", "MONGO_URI"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(vault.hvac, "Client", FakeClient)
    vault_client.cache_clear()
    app_secrets.cache_clear()
    yield
    vault_client.cache_clear()
    app_secrets.cache_clear()


def test_secret_without_vault_reads_the_environment(monkeypatch):
    # Arrange
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-from-env")

    # Act / Assert
    assert (secret("ANTHROPIC_API_KEY"), secret("MONGO_URI", "fallback"), vault_client()) == ("sk-from-env", "fallback", None)


# Production logs in with AppRole: the role id is configuration, and the secret id
# arrives as a mounted file, so it is never in an environment variable or an image.
@pytest.mark.parametrize("role_from_file", [True, False], ids=["role_id_file", "role_id_env"])
def test_vault_client_approle_reads_the_secret_id_from_its_file(monkeypatch, tmp_path, role_from_file):
    # Arrange
    (tmp_path / "secret_id").write_text("s3cret-id\n")
    (tmp_path / "role_id").write_text("role-1\n")
    monkeypatch.setenv("VAULT_ADDR", "http://vault:8200")
    monkeypatch.setenv("VAULT_SECRET_ID_FILE", str(tmp_path / "secret_id"))
    if role_from_file:
        monkeypatch.setenv("VAULT_ROLE_ID_FILE", str(tmp_path / "role_id"))
    else:
        monkeypatch.setenv("VAULT_ROLE_ID", "role-1")

    # Act
    client = vault_client()

    # Assert
    assert (client.url, client.logins, client.token) == ("http://vault:8200", [("role-1", "s3cret-id")], "approle-token")


def test_vault_client_dev_token_skips_the_approle_login(monkeypatch):
    # Arrange
    monkeypatch.setenv("VAULT_ADDR", "http://localhost:8200")
    monkeypatch.setenv("VAULT_TOKEN", "dev-root")

    # Act
    client = vault_client()

    # Assert
    assert (client.token, client.logins) == ("dev-root", [])


def test_secret_with_vault_prefers_vault_and_reads_it_once(monkeypatch):
    # Arrange
    monkeypatch.setenv("VAULT_ADDR", "http://localhost:8200")
    monkeypatch.setenv("VAULT_TOKEN", "dev-root")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-from-env")
    monkeypatch.setenv("MONGO_DB_NAME", "invoices_db")

    # Act
    values = (secret("ANTHROPIC_API_KEY"), secret("MONGO_URI"), secret("MONGO_DB_NAME"))

    # Assert
    assert values == ("sk-from-vault", "mongodb://app:pw@mongo:27017", "invoices_db")
    assert vault_client().reads == ["invoices-app"]
