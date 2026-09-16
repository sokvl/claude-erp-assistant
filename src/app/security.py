import secrets

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

from app.config import API_KEY

api_key_header = APIKeyHeader(name="X-API-Key")


def require_api_key(key: str = Security(api_key_header)):
    if not secrets.compare_digest(key.encode(), API_KEY.encode()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "APIKey"},
        )
