import logging
import secrets
from functools import cache

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from app.auth.roles import Principal
from app.auth.signer import LocalSigner, TokenSigner
from app.auth.tokens import InvalidToken, verify_access_token
from app.config import API_KEY

logger = logging.getLogger(__name__)

api_key_header = APIKeyHeader(name="X-API-Key")
bearer = HTTPBearer(auto_error=False)


def require_api_key(key: str = Security(api_key_header)):
    if not secrets.compare_digest(key.encode(), API_KEY.encode()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "APIKey"},
        )


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


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )
