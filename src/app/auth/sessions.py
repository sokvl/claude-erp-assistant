import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from app.limits import QUERY_TIMEOUT_MS, REFRESH_TOKEN_DAYS

REFRESH_TOKEN_COLLECTION = "refresh_tokens"


def digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_refresh_token(collection: Any, username: str, family_id: str | None, now: datetime) -> str:
    token = secrets.token_urlsafe(32)
    collection.insert_one(
        {
            "_id": digest(token),
            "username": username,
            "familyId": family_id or uuid4().hex,
            "createdAt": now,
            "expiresAt": now + timedelta(days=REFRESH_TOKEN_DAYS),
            "usedAt": None,
            "revokedAt": None,
        }
    )
    return token


def consume_refresh_token(collection: Any, token: str, now: datetime) -> dict[str, Any] | None:
    consumed = collection.find_one_and_update(
        {"_id": digest(token), "usedAt": None, "revokedAt": None, "expiresAt": {"$gt": now}},
        {"$set": {"usedAt": now}},
        maxTimeMS=QUERY_TIMEOUT_MS,
    )
    if consumed is None:
        replayed = collection.find_one({"_id": digest(token), "usedAt": {"$ne": None}}, max_time_ms=QUERY_TIMEOUT_MS)
        if replayed is not None:
            revoke_family(collection, replayed["familyId"], now)
    return consumed


def revoke_family(collection: Any, family_id: str, now: datetime) -> None:
    collection.update_many({"familyId": family_id, "revokedAt": None}, {"$set": {"revokedAt": now}})


def revoke_session(collection: Any, token: str, now: datetime) -> None:
    session = collection.find_one({"_id": digest(token)}, max_time_ms=QUERY_TIMEOUT_MS)
    if session is not None:
        revoke_family(collection, session["familyId"], now)
