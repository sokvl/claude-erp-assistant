import secrets
from datetime import datetime, timedelta
from typing import Any

from app.auth.sessions import digest
from app.limits import API_KEY_MAX_DAYS, QUERY_TIMEOUT_MS

API_KEY_COLLECTION = "api_keys"


def issue_api_key(collection: Any, username: str, name: str, now: datetime, days: int = API_KEY_MAX_DAYS) -> str:
    if not 1 <= days <= API_KEY_MAX_DAYS:
        raise ValueError(f"An API key lives 1-{API_KEY_MAX_DAYS} days")
    prefix = secrets.token_hex(4)
    key = f"ak_{prefix}_{secrets.token_urlsafe(32)}"
    collection.insert_one(
        {
            "_id": digest(key),
            "prefix": prefix,
            "username": username,
            "name": name,
            "createdAt": now,
            "expiresAt": now + timedelta(days=days),
            "revokedAt": None,
        }
    )
    return key


def api_key_owner(collection: Any, key: str, now: datetime) -> str | None:
    criteria = {"_id": digest(key), "revokedAt": None, "expiresAt": {"$gt": now}}
    document = collection.find_one(criteria, max_time_ms=QUERY_TIMEOUT_MS)
    return None if document is None else document["username"]


def revoke_api_key(collection: Any, username: str, prefix: str, now: datetime) -> bool:
    criteria = {"username": username, "prefix": prefix, "revokedAt": None}
    return collection.update_one(criteria, {"$set": {"revokedAt": now}}).matched_count > 0
