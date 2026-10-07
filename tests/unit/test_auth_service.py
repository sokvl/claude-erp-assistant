from datetime import UTC, datetime

import pytest
from argon2 import PasswordHasher
from memory_collection import MemoryCollection

from app.auth import service
from app.auth.passwords import verify_password
from app.auth.roles import Principal, Role
from app.auth.service import AuthError
from app.auth.sessions import digest
from app.auth.signer import LocalSigner
from app.auth.tokens import verify_access_token
from app.auth.users import create_user
from app.limits import MAX_LOGIN_ATTEMPTS

NOW = datetime.now(UTC)
PASSWORD = "correct horse battery staple"


@pytest.fixture
def db():
    database = {"users": MemoryCollection(), "login_attempts": MemoryCollection(), "refresh_tokens": MemoryCollection()}
    create_user(database["users"], "anna", PASSWORD, Role.MANAGER)
    return database


@pytest.fixture
def signer():
    return LocalSigner()


def test_login_valid_password_returns_a_verifiable_session(db, signer):
    # Arrange / Act
    session = service.login(db, signer, " Anna ", PASSWORD, NOW)

    # Assert
    assert session.principal == Principal("anna", Role.MANAGER)
    assert verify_access_token(session.access_token, signer.public_keys()) == session.principal
    assert db["refresh_tokens"].documents[digest(session.refresh_token)]["username"] == "anna"


@pytest.mark.parametrize(
    ("username", "password", "disabled"),
    [("anna", PASSWORD + "x", False), ("piotr", PASSWORD, False), ("anna", PASSWORD, True)],
    ids=["wrong_password", "unknown_user", "disabled_user"],
)
def test_login_rejected_raises_the_same_error_and_counts_a_failure(db, signer, username, password, disabled):
    # Arrange: one error for all three, so a response never tells which usernames exist
    db["users"].documents["anna"]["disabled"] = disabled

    # Act
    with pytest.raises(AuthError) as raised:
        service.login(db, signer, username, password, NOW)

    # Assert
    assert raised.value.code == "invalid_credentials"
    assert db["login_attempts"].documents[username]["failures"] == 1
    assert db["refresh_tokens"].documents == {}


def test_login_locked_username_rejects_even_the_right_password(db, signer):
    # Arrange
    for _ in range(MAX_LOGIN_ATTEMPTS):
        with pytest.raises(AuthError):
            service.login(db, signer, "anna", "wrong password", NOW)

    # Act
    with pytest.raises(AuthError) as raised:
        service.login(db, signer, "anna", PASSWORD, NOW)

    # Assert
    assert raised.value.code == "locked"


def test_login_success_clears_earlier_failures(db, signer):
    # Arrange
    with pytest.raises(AuthError):
        service.login(db, signer, "anna", "wrong password", NOW)

    # Act
    service.login(db, signer, "anna", PASSWORD, NOW)

    # Assert
    assert db["login_attempts"].documents == {}


def test_login_hash_with_outdated_parameters_is_replaced(db, signer):
    # Arrange
    weak = PasswordHasher(time_cost=1, memory_cost=8_192).hash(PASSWORD)
    db["users"].documents["anna"]["passwordHash"] = weak

    # Act
    service.login(db, signer, "anna", PASSWORD, NOW)

    # Assert
    stored = db["users"].documents["anna"]["passwordHash"]
    assert stored != weak
    assert verify_password(stored, PASSWORD) is True


def test_refresh_valid_token_rotates_it_within_the_same_family(db, signer):
    # Arrange
    first = service.login(db, signer, "anna", PASSWORD, NOW)

    # Act
    second = service.refresh(db, signer, first.refresh_token, NOW)

    # Assert
    tokens = db["refresh_tokens"].documents
    assert second.refresh_token != first.refresh_token
    assert tokens[digest(first.refresh_token)]["usedAt"] == NOW
    assert tokens[digest(second.refresh_token)]["familyId"] == tokens[digest(first.refresh_token)]["familyId"]
    assert verify_access_token(second.access_token, signer.public_keys()) == Principal("anna", Role.MANAGER)


# A role change reaches the next access token at refresh, not at the next login.
def test_refresh_reads_the_current_role(db, signer):
    # Arrange
    session = service.login(db, signer, "anna", PASSWORD, NOW)
    db["users"].documents["anna"]["role"] = "consultant"

    # Act
    refreshed = service.refresh(db, signer, session.refresh_token, NOW)

    # Assert
    assert refreshed.principal == Principal("anna", Role.CONSULTANT)


def test_refresh_disabled_user_raises_and_revokes_the_session(db, signer):
    # Arrange
    session = service.login(db, signer, "anna", PASSWORD, NOW)
    db["users"].documents["anna"]["disabled"] = True

    # Act
    with pytest.raises(AuthError) as raised:
        service.refresh(db, signer, session.refresh_token, NOW)

    # Assert
    assert raised.value.code == "invalid_refresh_token"
    assert all(doc["revokedAt"] == NOW for doc in db["refresh_tokens"].documents.values())


@pytest.mark.parametrize("token", ["made-up", ""], ids=["unknown", "empty"])
def test_refresh_unknown_token_raises(db, signer, token):
    # Arrange / Act / Assert
    with pytest.raises(AuthError, match="invalid_refresh_token"):
        service.refresh(db, signer, token, NOW)


def test_logout_revokes_the_session_so_refresh_fails(db, signer):
    # Arrange
    session = service.login(db, signer, "anna", PASSWORD, NOW)

    # Act
    service.logout(db, session.refresh_token, NOW)

    # Assert
    with pytest.raises(AuthError, match="invalid_refresh_token"):
        service.refresh(db, signer, session.refresh_token, NOW)
