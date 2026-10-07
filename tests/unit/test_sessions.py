from datetime import UTC, datetime, timedelta

from memory_collection import MemoryCollection

from app.auth.sessions import consume_refresh_token, digest, issue_refresh_token, revoke_session
from app.limits import REFRESH_TOKEN_DAYS

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


def test_issue_refresh_token_stores_only_its_digest():
    # Arrange
    sessions = MemoryCollection()

    # Act
    token = issue_refresh_token(sessions, "anna", None, NOW)

    # Assert
    [(key, stored)] = sessions.documents.items()
    assert key == digest(token) != token
    assert token not in str(stored)
    assert stored["expiresAt"] - stored["createdAt"] == timedelta(days=REFRESH_TOKEN_DAYS)


def test_consume_refresh_token_unused_marks_it_used_and_returns_it():
    # Arrange
    sessions = MemoryCollection()
    token = issue_refresh_token(sessions, "anna", "family-1", NOW)

    # Act
    consumed = consume_refresh_token(sessions, token, NOW)

    # Assert
    assert (consumed["username"], consumed["familyId"]) == ("anna", "family-1")
    assert sessions.documents[digest(token)]["usedAt"] == NOW


# A used token coming back means someone else holds a copy: every token of that
# session is revoked, so the thief's newer token dies with the victim's.
def test_consume_refresh_token_replayed_revokes_the_whole_family():
    # Arrange
    sessions = MemoryCollection()
    first = issue_refresh_token(sessions, "anna", "family-1", NOW)
    consume_refresh_token(sessions, first, NOW)
    second = issue_refresh_token(sessions, "anna", "family-1", NOW)
    other = issue_refresh_token(sessions, "piotr", "family-2", NOW)

    # Act
    replayed = consume_refresh_token(sessions, first, NOW)

    # Assert
    assert replayed is None
    assert consume_refresh_token(sessions, second, NOW) is None
    assert sessions.documents[digest(other)]["revokedAt"] is None


def test_consume_refresh_token_expired_returns_none():
    # Arrange
    sessions = MemoryCollection()
    token = issue_refresh_token(sessions, "anna", None, NOW)

    # Act
    consumed = consume_refresh_token(sessions, token, NOW + timedelta(days=REFRESH_TOKEN_DAYS, seconds=1))

    # Assert
    assert consumed is None


def test_consume_refresh_token_unknown_returns_none_and_revokes_nothing():
    # Arrange
    sessions = MemoryCollection()
    token = issue_refresh_token(sessions, "anna", None, NOW)

    # Act
    consumed = consume_refresh_token(sessions, "made-up", NOW)

    # Assert
    assert consumed is None
    assert sessions.documents[digest(token)]["revokedAt"] is None


def test_revoke_session_revokes_every_token_of_the_family():
    # Arrange
    sessions = MemoryCollection()
    first = issue_refresh_token(sessions, "anna", "family-1", NOW)
    consume_refresh_token(sessions, first, NOW)
    current = issue_refresh_token(sessions, "anna", "family-1", NOW)

    # Act
    revoke_session(sessions, current, NOW)

    # Assert
    assert [doc["revokedAt"] for doc in sessions.documents.values()] == [NOW, NOW]
    assert consume_refresh_token(sessions, current, NOW) is None


def test_revoke_session_unknown_token_changes_nothing():
    # Arrange
    sessions = MemoryCollection()
    token = issue_refresh_token(sessions, "anna", None, NOW)

    # Act
    revoke_session(sessions, "made-up", NOW)

    # Assert
    assert sessions.documents[digest(token)]["revokedAt"] is None
