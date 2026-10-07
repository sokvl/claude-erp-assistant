import logging
from collections.abc import Callable
from datetime import UTC, datetime
from functools import cache

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from pymongo.database import Database

from app.auth.api_keys import API_KEY_COLLECTION, api_key_owner
from app.auth.roles import Principal, Role, allows
from app.auth.signer import LocalSigner, TokenSigner
from app.auth.tokens import InvalidToken, verify_access_token
from app.auth.users import USER_COLLECTION, find_user
from app.auth.vault_signer import VaultTransitSigner
from app.db import get_database
from app.vault import vault_client

logger = logging.getLogger(__name__)

bearer = HTTPBearer(auto_error=False)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


@cache
def get_signer() -> TokenSigner:
    if vault_client() is not None:
        return VaultTransitSigner(vault_client, vault_client.cache_clear)
    logger.warning("signing access tokens with an in-memory key; they stop verifying when the process restarts")
    return LocalSigner()


def current_principal(
    credentials: HTTPAuthorizationCredentials | None = Security(bearer),
    api_key: str | None = Security(api_key_header),
    signer: TokenSigner = Depends(get_signer),
    db: Database = Depends(get_database),
) -> Principal:
    if credentials is not None:
        try:
            return verify_access_token(credentials.credentials, signer.public_keys())
        except InvalidToken as exc:
            raise _unauthorized("Invalid or expired token") from exc
    if api_key:
        return _api_key_principal(db, api_key)
    raise _unauthorized("Not authenticated")


@cache
def require_role(required: Role) -> Callable[..., Principal]:
    def dependency(principal: Principal = Depends(current_principal)) -> Principal:
        if not allows(principal.role, required):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Requires the {required} role")
        return principal

    return dependency


def _api_key_principal(db: Database, key: str) -> Principal:
    username = api_key_owner(db[API_KEY_COLLECTION], key, datetime.now(UTC))
    user = None if username is None else find_user(db[USER_COLLECTION], username)
    if user is None or user["disabled"]:
        raise _unauthorized("Invalid or expired API key")
    return Principal(user["_id"], Role(user["role"]))


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )
