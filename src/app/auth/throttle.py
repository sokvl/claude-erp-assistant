from datetime import datetime, timedelta
from typing import Any

from app.limits import LOGIN_LOCKOUT_MINUTES, MAX_LOGIN_ATTEMPTS, QUERY_TIMEOUT_MS

LOGIN_ATTEMPT_COLLECTION = "login_attempts"


def is_locked(collection: Any, username: str, now: datetime) -> bool:
    criteria = {"_id": username, "failures": {"$gte": MAX_LOGIN_ATTEMPTS}, "expiresAt": {"$gt": now}}
    return collection.find_one(criteria, max_time_ms=QUERY_TIMEOUT_MS) is not None


def record_failure(collection: Any, username: str, now: datetime) -> None:
    collection.delete_one({"_id": username, "expiresAt": {"$lte": now}})
    collection.update_one(
        {"_id": username},
        {"$inc": {"failures": 1}, "$set": {"expiresAt": now + timedelta(minutes=LOGIN_LOCKOUT_MINUTES)}},
        upsert=True,
    )


def clear_failures(collection: Any, username: str) -> None:
    collection.delete_one({"_id": username})
