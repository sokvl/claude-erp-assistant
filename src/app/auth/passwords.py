from functools import cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.limits import MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH

_hasher = PasswordHasher()


@cache
def _dummy_hash() -> str:
    return _hasher.hash("dummy password for unknown users")


def validate_password(password: str) -> None:
    if not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
        raise ValueError(f"Password must be {MIN_PASSWORD_LENGTH}-{MAX_PASSWORD_LENGTH} characters")


def hash_password(password: str) -> str:
    validate_password(password)
    return _hasher.hash(password)


def verify_password(stored_hash: str | None, password: str) -> bool:
    if len(password) > MAX_PASSWORD_LENGTH:
        return False
    try:
        matched = _hasher.verify(stored_hash or _dummy_hash(), password)
    except (VerificationError, InvalidHashError):
        return False
    return matched and stored_hash is not None


def needs_rehash(stored_hash: str) -> bool:
    return _hasher.check_needs_rehash(stored_hash)
