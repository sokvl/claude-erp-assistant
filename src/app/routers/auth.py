from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field
from pymongo.database import Database

from app.auth import service
from app.auth.roles import Principal
from app.auth.service import AuthError, Session
from app.auth.signer import TokenSigner
from app.db import get_database
from app.limits import ACCESS_TOKEN_MINUTES, MAX_PASSWORD_LENGTH, MAX_TEXT_LENGTH, REFRESH_TOKEN_DAYS
from app.security import current_principal, get_signer

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "refresh_token"
COOKIE_PATH = "/auth"

AUTH_ERRORS = {
    "invalid_credentials": (status.HTTP_401_UNAUTHORIZED, "Invalid username or password"),
    "locked": (status.HTTP_429_TOO_MANY_REQUESTS, "Too many failed attempts; try again later"),
    "invalid_refresh_token": (status.HTTP_401_UNAUTHORIZED, "Session expired; log in again"),
}


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=MAX_TEXT_LENGTH)
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)


def _issue(response: Response, session: Session) -> dict[str, Any]:
    response.set_cookie(
        REFRESH_COOKIE,
        session.refresh_token,
        max_age=REFRESH_TOKEN_DAYS * 24 * 60 * 60,
        httponly=True,
        secure=True,
        samesite="strict",
        path=COOKIE_PATH,
    )
    return {
        "access_token": session.access_token,
        "token_type": "bearer",
        "expires_in": ACCESS_TOKEN_MINUTES * 60,
        "username": session.principal.username,
        "role": session.principal.role,
    }


def _rejected(exc: AuthError) -> HTTPException:
    code, detail = AUTH_ERRORS[exc.code]
    headers = {"WWW-Authenticate": "Bearer"} if code == status.HTTP_401_UNAUTHORIZED else None
    return HTTPException(status_code=code, detail=detail, headers=headers)


@router.post("/login")
def login(
    body: LoginRequest,
    response: Response,
    db: Database = Depends(get_database),
    signer: TokenSigner = Depends(get_signer),
):
    try:
        session = service.login(db, signer, body.username, body.password, datetime.now(UTC))
    except AuthError as exc:
        raise _rejected(exc) from exc
    return _issue(response, session)


@router.post("/refresh")
def refresh(
    response: Response,
    refresh_token: str | None = Cookie(None),
    db: Database = Depends(get_database),
    signer: TokenSigner = Depends(get_signer),
):
    if not refresh_token:
        raise _rejected(AuthError("invalid_refresh_token"))
    try:
        session = service.refresh(db, signer, refresh_token, datetime.now(UTC))
    except AuthError as exc:
        response.delete_cookie(REFRESH_COOKIE, path=COOKIE_PATH)
        raise _rejected(exc) from exc
    return _issue(response, session)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    refresh_token: str | None = Cookie(None),
    db: Database = Depends(get_database),
) -> None:
    if refresh_token:
        service.logout(db, refresh_token, datetime.now(UTC))
    response.delete_cookie(REFRESH_COOKIE, path=COOKIE_PATH, secure=True, httponly=True, samesite="strict")


@router.get("/me")
def me(principal: Principal = Depends(current_principal)):
    return {"username": principal.username, "role": principal.role}
