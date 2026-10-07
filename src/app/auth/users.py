import re
from datetime import UTC, datetime
from typing import Any

from pymongo.errors import DuplicateKeyError

from app.auth.passwords import hash_password
from app.auth.roles import Role
from app.limits import MAX_TEXT_LENGTH, QUERY_TIMEOUT_MS

USER_COLLECTION = "users"

USERNAME_PATTERN = re.compile(rf"[a-z0-9][a-z0-9._-]{{2,{MAX_TEXT_LENGTH - 1}}}")


def normalize_username(username: str) -> str:
    normalized = username.strip().lower()
    if not USERNAME_PATTERN.fullmatch(normalized):
        raise ValueError(f"Username must be 3-{MAX_TEXT_LENGTH} characters of a-z, 0-9, '.', '_' or '-'")
    return normalized


def create_user(collection: Any, username: str, password: str, role: Role) -> str:
    username = normalize_username(username)
    now = datetime.now(UTC)
    document = {
        "_id": username,
        "passwordHash": hash_password(password),
        "role": str(role),
        "disabled": False,
        "createdAt": now,
        "passwordChangedAt": now,
    }
    try:
        collection.insert_one(document)
    except DuplicateKeyError as exc:
        raise ValueError(f"User {username!r} already exists") from exc
    return username


def find_user(collection: Any, username: str) -> dict[str, Any] | None:
    return collection.find_one({"_id": username.strip().lower()}, max_time_ms=QUERY_TIMEOUT_MS)


def replace_password_hash(collection: Any, username: str, password_hash: str) -> None:
    collection.update_one({"_id": username}, {"$set": {"passwordHash": password_hash}})
