import base64
from datetime import UTC, datetime

import hvac.exceptions
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from app.auth.roles import Principal, Role
from app.auth.tokens import InvalidToken, issue_access_token, verify_access_token
from app.auth.vault_signer import VaultTransitSigner
from app.limits import MIN_SIGNING_KEY_RELOAD_SECONDS, SIGNING_KEY_CACHE_SECONDS

MANAGER = Principal("anna", Role.MANAGER)


class FakeTransit:
    def __init__(self):
        self.private = {1: Ed25519PrivateKey.generate()}
        self.min_decryption_version = 1
        self.reads = 0
        self.forbid_next = False

    def rotate(self):
        self.private[max(self.private) + 1] = Ed25519PrivateKey.generate()

    def read_key(self, name):
        self._check()
        self.reads += 1
        raw = {version: key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw) for version, key in self.private.items()}
        return {"data": {
            "latest_version": max(self.private),
            "min_decryption_version": self.min_decryption_version,
            "keys": {str(version): {"public_key": base64.b64encode(value).decode()} for version, value in raw.items()},
        }}

    def sign_data(self, name, hash_input, key_version, marshaling_algorithm):
        self._check()
        signature = self.private[key_version].sign(base64.b64decode(hash_input))
        return {"data": {"signature": f"vault:v{key_version}:{base64.urlsafe_b64encode(signature).rstrip(b'=').decode()}"}}

    def _check(self):
        if self.forbid_next:
            self.forbid_next = False
            raise hvac.exceptions.Forbidden("token expired")


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


@pytest.fixture
def transit():
    return FakeTransit()


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def reconnects():
    return []


@pytest.fixture
def signer(transit, clock, reconnects):
    client = type("Client", (), {"secrets": type("Secrets", (), {"transit": transit})()})()
    return VaultTransitSigner(lambda: client, lambda: reconnects.append(True), clock=clock)


def test_vault_signer_token_round_trips_with_the_latest_key_version(signer):
    # Arrange / Act
    token = issue_access_token(MANAGER, signer, datetime.now(UTC))

    # Assert
    assert signer.current_kid() == "app-jwt:v1"
    assert verify_access_token(token, signer.public_keys()) == MANAGER


# Rotation logs nobody out: tokens signed with v1 keep verifying next to v2 until
# min_decryption_version is raised, which is the runbook's last step.
def test_vault_signer_after_rotation_old_tokens_verify_until_their_version_is_retired(signer, transit, clock):
    # Arrange
    old = issue_access_token(MANAGER, signer, datetime.now(UTC))
    transit.rotate()
    clock.now += SIGNING_KEY_CACHE_SECONDS

    # Act
    new = issue_access_token(MANAGER, signer, datetime.now(UTC))
    still_valid = verify_access_token(old, signer.public_keys())
    transit.min_decryption_version = 2
    clock.now += SIGNING_KEY_CACHE_SECONDS

    # Assert
    assert (signer.current_kid(), still_valid) == ("app-jwt:v2", MANAGER)
    assert verify_access_token(new, signer.public_keys()) == MANAGER
    with pytest.raises(InvalidToken):
        verify_access_token(old, signer.public_keys())


# Another worker may rotate before this one's cache expires; an unknown kid reloads
# the keys at once instead of rejecting valid tokens for the rest of the cache window.
def test_vault_signer_unknown_kid_reloads_the_keys_once(signer, transit, clock):
    # Arrange
    signer.current_kid()
    transit.rotate()
    other_worker = VaultTransitSigner(lambda: type("C", (), {"secrets": type("S", (), {"transit": transit})()})(), lambda: None)
    token = issue_access_token(MANAGER, other_worker, datetime.now(UTC))
    clock.now += MIN_SIGNING_KEY_RELOAD_SECONDS

    # Act
    principal = verify_access_token(token, signer.public_keys())

    # Assert
    assert principal == MANAGER


def test_vault_signer_unknown_kid_reloads_at_most_once_per_window(signer, transit):
    # Arrange: a flood of made-up kids must not turn into a Vault read per request
    signer.current_kid()
    reads = transit.reads

    # Act
    for _ in range(5):
        with pytest.raises(KeyError):
            signer.public_keys()["app-jwt:v99"]

    # Assert
    assert transit.reads == reads


def test_vault_signer_keys_are_cached_between_requests(signer, transit, clock):
    # Arrange
    signer.current_kid()

    # Act
    clock.now += SIGNING_KEY_CACHE_SECONDS - 1
    signer.public_keys()
    cached_reads = transit.reads
    clock.now += 1
    signer.public_keys()

    # Assert
    assert (cached_reads, transit.reads) == (1, 2)


# An AppRole token expires; the first Forbidden logs in again and retries once.
def test_vault_signer_forbidden_reconnects_and_retries(signer, transit, reconnects):
    # Arrange
    transit.forbid_next = True

    # Act
    kid = signer.current_kid()

    # Assert
    assert (kid, reconnects) == ("app-jwt:v1", [True])
