import pytest
from pymongo.errors import DuplicateKeyError

from app.auth.passwords import verify_password
from app.auth.roles import Role
from app.auth.users import create_user, find_user
from app.limits import MAX_TEXT_LENGTH, QUERY_TIMEOUT_MS

PASSWORD = "correct horse battery staple"


class Users:
    def __init__(self):
        self.documents = {}
        self.kwargs = []

    def insert_one(self, document):
        if document["_id"] in self.documents:
            raise DuplicateKeyError("E11000 duplicate key")
        self.documents[document["_id"]] = document

    def find_one(self, criteria, **kwargs):
        self.kwargs.append(kwargs)
        return self.documents.get(criteria["_id"])


def test_create_user_stores_a_normalized_enabled_account_with_a_password_hash():
    # Arrange
    users = Users()

    # Act
    username = create_user(users, "  Anna.Nowak ", PASSWORD, Role.MANAGER)

    # Assert
    stored = users.documents["anna.nowak"]
    assert username == "anna.nowak"
    assert (stored["role"], stored["disabled"]) == ("manager", False)
    assert verify_password(stored["passwordHash"], PASSWORD) is True
    assert stored["createdAt"] == stored["passwordChangedAt"]


# _id is the username, so uniqueness comes from the _id index that always exists,
# whether or not anyone ran the index loader.
def test_create_user_existing_username_raises_value_error():
    # Arrange
    users = Users()
    create_user(users, "anna", PASSWORD, Role.CONSULTANT)

    # Act / Assert
    with pytest.raises(ValueError, match="already exists"):
        create_user(users, "ANNA", PASSWORD, Role.MANAGER)


@pytest.mark.parametrize(
    "username",
    ["ab", "x" * (MAX_TEXT_LENGTH + 1), "anna nowak", "-anna", "anna$", ""],
    ids=["too_short", "too_long", "space", "leading_dash", "symbol", "empty"],
)
def test_create_user_invalid_username_raises_value_error_and_stores_nothing(username):
    # Arrange
    users = Users()

    # Act / Assert
    with pytest.raises(ValueError, match="Username must be"):
        create_user(users, username, PASSWORD, Role.CONSULTANT)
    assert users.documents == {}


def test_create_user_short_password_stores_nothing():
    # Arrange
    users = Users()

    # Act / Assert
    with pytest.raises(ValueError, match="Password must be"):
        create_user(users, "anna", "short", Role.CONSULTANT)
    assert users.documents == {}


@pytest.mark.parametrize(
    ("lookup", "found"),
    [("anna", True), (" ANNA ", True), ("piotr", False)],
    ids=["exact", "case_and_spaces", "unknown"],
)
def test_find_user_matches_the_normalized_username(lookup, found):
    # Arrange
    users = Users()
    create_user(users, "anna", PASSWORD, Role.CONSULTANT)

    # Act
    user = find_user(users, lookup)

    # Assert
    assert (user is not None) is found
    assert users.kwargs[-1] == {"max_time_ms": QUERY_TIMEOUT_MS}
