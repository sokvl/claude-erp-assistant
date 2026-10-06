from dataclasses import dataclass
from datetime import datetime

from app.auth.passwords import hash_password, needs_rehash, verify_password
from app.auth.roles import Principal, Role
from app.auth.sessions import (
    REFRESH_TOKEN_COLLECTION,
    consume_refresh_token,
    issue_refresh_token,
    revoke_family,
    revoke_session,
)
from app.auth.signer import TokenSigner
from app.auth.throttle import LOGIN_ATTEMPT_COLLECTION, clear_failures, is_locked, record_failure
from app.auth.tokens import issue_access_token
from app.auth.users import USER_COLLECTION, find_user, replace_password_hash
from app.utils.mongo import CollectionSource


class AuthError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Session:
    access_token: str
    refresh_token: str
    principal: Principal


def login(db: CollectionSource, signer: TokenSigner, username: str, password: str, now: datetime) -> Session:
    name = username.strip().lower()
    attempts = db[LOGIN_ATTEMPT_COLLECTION]
    if is_locked(attempts, name, now):
        raise AuthError("locked")
    user = find_user(db[USER_COLLECTION], name)
    if not verify_password(user["passwordHash"] if user else None, password) or user["disabled"]:
        record_failure(attempts, name, now)
        raise AuthError("invalid_credentials")
    clear_failures(attempts, name)
    if needs_rehash(user["passwordHash"]):
        replace_password_hash(db[USER_COLLECTION], user["_id"], hash_password(password))
    principal = Principal(user["_id"], Role(user["role"]))
    refresh_token = issue_refresh_token(db[REFRESH_TOKEN_COLLECTION], principal.username, None, now)
    return Session(issue_access_token(principal, signer, now), refresh_token, principal)


def refresh(db: CollectionSource, signer: TokenSigner, token: str, now: datetime) -> Session:
    sessions = db[REFRESH_TOKEN_COLLECTION]
    consumed = consume_refresh_token(sessions, token, now)
    if consumed is None:
        raise AuthError("invalid_refresh_token")
    user = find_user(db[USER_COLLECTION], consumed["username"])
    if user is None or user["disabled"]:
        revoke_family(sessions, consumed["familyId"], now)
        raise AuthError("invalid_refresh_token")
    principal = Principal(user["_id"], Role(user["role"]))
    refresh_token = issue_refresh_token(sessions, principal.username, consumed["familyId"], now)
    return Session(issue_access_token(principal, signer, now), refresh_token, principal)


def logout(db: CollectionSource, token: str, now: datetime) -> None:
    revoke_session(db[REFRESH_TOKEN_COLLECTION], token, now)
