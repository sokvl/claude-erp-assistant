from datetime import UTC, datetime, timedelta

import pytest
from memory_collection import MemoryCollection

from app.auth.api_keys import api_key_owner, issue_api_key, revoke_api_key
from app.auth.sessions import digest
from app.limits import API_KEY_MAX_DAYS

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)


def test_issue_api_key_stores_only_its_digest_and_a_short_prefix():
    # Arrange
    keys = MemoryCollection()

    # Act
    key = issue_api_key(keys, "anna", "evals", NOW)

    # Assert
    stored = keys.documents[digest(key)]
    assert key.startswith(f"ak_{stored['prefix']}_")
    assert key not in str(stored)
    assert (stored["username"], stored["name"]) == ("anna", "evals")
    assert stored["expiresAt"] - stored["createdAt"] == timedelta(days=API_KEY_MAX_DAYS)


@pytest.mark.parametrize("days", [0, API_KEY_MAX_DAYS + 1], ids=["zero", "over_max"])
def test_issue_api_key_lifetime_out_of_bounds_raises_and_stores_nothing(days):
    # Arrange
    keys = MemoryCollection()

    # Act / Assert
    with pytest.raises(ValueError, match=f"1-{API_KEY_MAX_DAYS} days"):
        issue_api_key(keys, "anna", "evals", NOW, days)
    assert keys.documents == {}


@pytest.mark.parametrize(
    ("make_key", "at", "expected"),
    [
        (lambda key: key, NOW, "anna"),
        (lambda key: key + "x", NOW, None),
        (lambda key: key, NOW + timedelta(days=API_KEY_MAX_DAYS, seconds=1), None),
    ],
    ids=["valid", "unknown", "expired"],
)
def test_api_key_owner_returns_the_username_only_for_a_live_key(make_key, at, expected):
    # Arrange
    keys = MemoryCollection()
    key = issue_api_key(keys, "anna", "evals", NOW)

    # Act
    owner = api_key_owner(keys, make_key(key), at)

    # Assert
    assert owner == expected


# Rotation without downtime: a new key works alongside the old one until the old
# one is revoked, and revoking one key leaves the other alone.
def test_revoke_api_key_ends_only_that_key():
    # Arrange
    keys = MemoryCollection()
    old = issue_api_key(keys, "anna", "evals", NOW)
    new = issue_api_key(keys, "anna", "evals", NOW)

    # Act
    revoked = revoke_api_key(keys, "anna", keys.documents[digest(old)]["prefix"], NOW)

    # Assert
    assert revoked is True
    assert (api_key_owner(keys, old, NOW), api_key_owner(keys, new, NOW)) == (None, "anna")


@pytest.mark.parametrize(("username", "prefix"), [("piotr", None), ("anna", "00000000")], ids=["other_user", "unknown_prefix"])
def test_revoke_api_key_not_owned_returns_false_and_keeps_it(username, prefix):
    # Arrange
    keys = MemoryCollection()
    key = issue_api_key(keys, "anna", "evals", NOW)

    # Act
    revoked = revoke_api_key(keys, username, prefix or keys.documents[digest(key)]["prefix"], NOW)

    # Assert
    assert revoked is False
    assert api_key_owner(keys, key, NOW) == "anna"
