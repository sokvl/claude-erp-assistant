from datetime import UTC, datetime, timedelta

from memory_collection import MemoryCollection

from app.auth.throttle import clear_failures, is_locked, record_failure
from app.limits import LOGIN_LOCKOUT_MINUTES, MAX_LOGIN_ATTEMPTS

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


def _fail(attempts, times, now=NOW):
    for _ in range(times):
        record_failure(attempts, "anna", now)


def test_is_locked_below_the_limit_returns_false():
    # Arrange
    attempts = MemoryCollection()
    _fail(attempts, MAX_LOGIN_ATTEMPTS - 1)

    # Act / Assert
    assert is_locked(attempts, "anna", NOW) is False


def test_is_locked_at_the_limit_returns_true_only_for_that_username():
    # Arrange
    attempts = MemoryCollection()
    _fail(attempts, MAX_LOGIN_ATTEMPTS)

    # Act / Assert
    assert (is_locked(attempts, "anna", NOW), is_locked(attempts, "piotr", NOW)) == (True, False)


# The TTL sweep runs about once a minute, so an expired record can still be there:
# the lock reads expiresAt, and the next failure starts a fresh count.
def test_is_locked_after_the_window_returns_false_and_counting_restarts():
    # Arrange
    attempts = MemoryCollection()
    _fail(attempts, MAX_LOGIN_ATTEMPTS)
    later = NOW + timedelta(minutes=LOGIN_LOCKOUT_MINUTES, seconds=1)

    # Act
    unlocked = is_locked(attempts, "anna", later)
    record_failure(attempts, "anna", later)

    # Assert
    assert unlocked is False
    assert attempts.documents["anna"]["failures"] == 1


def test_clear_failures_after_a_success_resets_the_count():
    # Arrange
    attempts = MemoryCollection()
    _fail(attempts, MAX_LOGIN_ATTEMPTS - 1)

    # Act
    clear_failures(attempts, "anna")
    _fail(attempts, 1)

    # Assert
    assert attempts.documents["anna"]["failures"] == 1
