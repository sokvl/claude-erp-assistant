from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from memory_collection import MemoryCollection

from app.auth.api_keys import issue_api_key, revoke_api_key
from app.auth.roles import Principal, Role
from app.auth.signer import LocalSigner
from app.auth.tokens import issue_access_token
from app.auth.users import create_user
from app.security import current_principal, require_role

MANAGER = Principal("anna", Role.MANAGER)


def _credentials(token):
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def _authenticate(credentials=None, api_key=None, signer=None, db=None):
    db = db if db is not None else {"api_keys": MemoryCollection(), "users": MemoryCollection()}
    return current_principal(credentials=credentials, api_key=api_key, signer=signer or LocalSigner(), db=db)


@pytest.fixture
def db():
    database = {"api_keys": MemoryCollection(), "users": MemoryCollection()}
    create_user(database["users"], "anna", "correct horse battery staple", Role.MANAGER)
    return database


def test_current_principal_valid_token_returns_its_principal():
    # Arrange
    signer = LocalSigner()
    token = issue_access_token(MANAGER, signer, datetime.now(UTC))

    # Act
    principal = _authenticate(_credentials(token), signer=signer)

    # Assert
    assert principal == MANAGER


@pytest.mark.parametrize(
    ("credentials", "detail"),
    [(None, "Not authenticated"), (_credentials("not-a-token"), "Invalid or expired token")],
    ids=["missing", "invalid"],
)
def test_current_principal_without_a_valid_token_raises_401_with_a_bearer_challenge(credentials, detail):
    # Arrange / Act
    with pytest.raises(HTTPException) as raised:
        _authenticate(credentials)

    # Assert
    assert (raised.value.status_code, raised.value.detail, raised.value.headers) == (
        401, detail, {"WWW-Authenticate": "Bearer"},
    )


def test_current_principal_api_key_returns_its_owner_with_the_current_role(db):
    # Arrange
    key = issue_api_key(db["api_keys"], "anna", "evals", datetime.now(UTC))
    db["users"].documents["anna"]["role"] = "consultant"

    # Act
    principal = _authenticate(api_key=key, db=db)

    # Assert
    assert principal == Principal("anna", Role.CONSULTANT)


def _revoked(db, key):
    revoke_api_key(db["api_keys"], "anna", key.split("_")[1], datetime.now(UTC))
    return key


def _disabled_owner(db, key):
    db["users"].documents["anna"]["disabled"] = True
    return key


def _deleted_owner(db, key):
    db["users"].documents.clear()
    return key


@pytest.mark.parametrize(
    "present",
    [lambda db, key: "ak_00000000_made-up", _revoked, _disabled_owner, _deleted_owner],
    ids=["unknown_key", "revoked_key", "disabled_owner", "deleted_owner"],
)
def test_current_principal_unusable_api_key_raises_401(db, present):
    # Arrange
    key = present(db, issue_api_key(db["api_keys"], "anna", "evals", datetime.now(UTC)))

    # Act
    with pytest.raises(HTTPException) as raised:
        _authenticate(api_key=key, db=db)

    # Assert
    assert (raised.value.status_code, raised.value.headers) == (401, {"WWW-Authenticate": "Bearer"})


# A browser never sends a key and a script never sends a token, but when both
# arrive the token decides, so a stale key in a header cannot override a session.
def test_current_principal_token_and_api_key_uses_the_token(db):
    # Arrange
    signer = LocalSigner()
    token = issue_access_token(Principal("piotr", Role.CONSULTANT), signer, datetime.now(UTC))
    key = issue_api_key(db["api_keys"], "anna", "evals", datetime.now(UTC))

    # Act
    principal = _authenticate(_credentials(token), key, signer, db)

    # Assert
    assert principal == Principal("piotr", Role.CONSULTANT)


@pytest.mark.parametrize(
    ("role", "required", "allowed"),
    [
        (Role.MANAGER, Role.CONSULTANT, True),
        (Role.CONSULTANT, Role.MANAGER, False),
        (Role.ADMIN, Role.CONSULTANT, False),
    ],
    ids=["manager_on_consultant_route", "consultant_on_manager_route", "admin_on_consultant_route"],
)
def test_require_role_lets_through_only_roles_that_grant_it(role, required, allowed):
    # Arrange
    principal = Principal("anna", role)

    # Act
    try:
        result = require_role(required)(principal)
    except HTTPException as exc:
        result = exc.status_code

    # Assert
    assert result == (principal if allowed else 403)


# FastAPI caches a dependency per request by identity, so the same factory call must
# return the same function or the token would be verified once per use.
def test_require_role_returns_one_dependency_per_role():
    # Arrange / Act / Assert
    assert require_role(Role.MANAGER) is require_role(Role.MANAGER)
