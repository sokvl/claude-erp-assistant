import os
from datetime import UTC, datetime
from itertools import count
from uuid import uuid4

import hvac
import pytest
from hvac.exceptions import InvalidRequest, VaultError

from app.auth.roles import Principal, Role
from app.auth.tokens import InvalidToken, issue_access_token, verify_access_token
from app.auth.vault_signer import VaultTransitSigner
from app.limits import SIGNING_KEY_CACHE_SECONDS

pytestmark = pytest.mark.vault

ADDRESS = os.environ.get("VAULT_TEST_ADDR", "http://127.0.0.1:8200")
MANAGER = Principal("anna", Role.MANAGER)


@pytest.fixture
def vault():
    client = hvac.Client(url=ADDRESS, token=os.environ.get("VAULT_TEST_TOKEN", "dev-root-token"), timeout=2)
    try:
        authenticated = client.is_authenticated()
    except Exception:
        authenticated = False
    if not authenticated:
        if os.environ.get("REQUIRE_VAULT"):
            pytest.fail(f"Vault not reachable at {ADDRESS}")
        pytest.skip(f"Vault not reachable at {ADDRESS}")
    try:
        client.sys.enable_secrets_engine("transit")
    except InvalidRequest:
        pass
    return client


@pytest.fixture
def key_name(vault):
    name = f"test-jwt-{uuid4().hex[:8]}"
    vault.secrets.transit.create_key(name, key_type="ed25519")
    yield name
    vault.secrets.transit.update_key_configuration(name, deletion_allowed=True)
    vault.secrets.transit.delete_key(name)


def _signer(vault, key_name):
    ticks = count(step=SIGNING_KEY_CACHE_SECONDS)
    return VaultTransitSigner(lambda: vault, lambda: None, key_name=key_name, clock=lambda: float(next(ticks)))


def test_transit_signed_token_verifies_locally(vault, key_name):
    # Arrange
    signer = _signer(vault, key_name)

    # Act
    token = issue_access_token(MANAGER, signer, datetime.now(UTC))

    # Assert
    assert verify_access_token(token, signer.public_keys()) == MANAGER


def test_transit_rotation_keeps_old_tokens_until_their_version_is_retired(vault, key_name):
    # Arrange
    signer = _signer(vault, key_name)
    old = issue_access_token(MANAGER, signer, datetime.now(UTC))

    # Act
    vault.secrets.transit.rotate_key(key_name)
    new = issue_access_token(MANAGER, signer, datetime.now(UTC))
    old_after_rotation = verify_access_token(old, signer.public_keys())
    vault.secrets.transit.update_key_configuration(key_name, min_decryption_version=2)

    # Assert
    assert new.split(".")[0] != old.split(".")[0]
    assert old_after_rotation == MANAGER
    assert verify_access_token(new, signer.public_keys()) == MANAGER
    with pytest.raises(InvalidToken):
        verify_access_token(old, signer.public_keys())


def test_transit_signing_needs_the_key_to_exist(vault):
    # Arrange
    signer = _signer(vault, f"missing-{uuid4().hex[:8]}")

    # Act / Assert
    with pytest.raises(VaultError):
        signer.current_kid()
