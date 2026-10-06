from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.auth.roles import Principal, Role
from app.auth.signer import LocalSigner
from app.auth.tokens import issue_access_token
from app.security import current_principal, require_role

MANAGER = Principal("anna", Role.MANAGER)


def _credentials(token):
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def test_current_principal_valid_token_returns_its_principal():
    # Arrange
    signer = LocalSigner()
    token = issue_access_token(MANAGER, signer, datetime.now(UTC))

    # Act
    principal = current_principal(_credentials(token), signer)

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
        current_principal(credentials, LocalSigner())

    # Assert
    assert (raised.value.status_code, raised.value.detail, raised.value.headers) == (
        401, detail, {"WWW-Authenticate": "Bearer"},
    )


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
