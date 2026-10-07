import pytest
from argon2 import PasswordHasher

from app.auth.passwords import hash_password, needs_rehash, verify_password
from app.limits import MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH

PASSWORD = "correct horse battery staple"


def test_hash_password_never_stores_the_password_and_verifies_it():
    # Arrange / Act
    stored = hash_password(PASSWORD)

    # Assert
    assert PASSWORD not in stored
    assert stored.startswith("$argon2id$")
    assert verify_password(stored, PASSWORD) is True


@pytest.mark.parametrize(
    ("stored", "password"),
    [
        (hash_password(PASSWORD), PASSWORD + "x"),
        (None, PASSWORD),
        ("not-a-hash", PASSWORD),
        (hash_password(PASSWORD), "x" * (MAX_PASSWORD_LENGTH + 1)),
    ],
    ids=["wrong_password", "unknown_user", "corrupt_hash", "over_max_length"],
)
def test_verify_password_mismatch_returns_false_without_raising(stored, password):
    # Arrange: an unknown user still pays for one argon2 verify, so timing does not reveal the name
    # Act
    matched = verify_password(stored, password)

    # Assert
    assert matched is False


@pytest.mark.parametrize(
    "password",
    ["x" * (MIN_PASSWORD_LENGTH - 1), "x" * (MAX_PASSWORD_LENGTH + 1)],
    ids=["too_short", "too_long"],
)
def test_hash_password_out_of_bounds_raises_value_error(password):
    # Arrange / Act / Assert: the upper bound keeps one request from making argon2 hash megabytes
    with pytest.raises(ValueError, match="Password must be"):
        hash_password(password)


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        (hash_password(PASSWORD), False),
        (PasswordHasher(time_cost=1, memory_cost=8_192).hash(PASSWORD), True),
    ],
    ids=["current_parameters", "weaker_parameters"],
)
def test_needs_rehash_reports_hashes_made_with_older_parameters(stored, expected):
    # Arrange / Act
    outdated = needs_rehash(stored)

    # Assert
    assert outdated is expected
