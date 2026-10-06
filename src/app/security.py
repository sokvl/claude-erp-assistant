import logging
from collections.abc import Callable
from functools import cache

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.roles import Principal, Role, allows
from app.auth.signer import LocalSigner, TokenSigner
from app.auth.tokens import InvalidToken, verify_access_token

logger = logging.getLogger(__name__)

bearer = HTTPBearer(auto_error=False)


@cache
def get_signer() -> TokenSigner:
    logger.warning("signing access tokens with an in-memory key; they stop verifying when the process restarts")
    return LocalSigner()


def current_principal(
    credentials: HTTPAuthorizationCredentials | None = Security(bearer),
    signer: TokenSigner = Depends(get_signer),
) -> Principal:
    if credentials is None:
        raise _unauthorized("Not authenticated")
    try:
        return verify_access_token(credentials.credentials, signer.public_keys())
    except InvalidToken as exc:
        raise _unauthorized("Invalid or expired token") from exc


@cache
def require_role(required: Role) -> Callable[..., Principal]:
    def dependency(principal: Principal = Depends(current_principal)) -> Principal:
        if not allows(principal.role, required):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Requires the {required} role")
        return principal

    return dependency


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )
