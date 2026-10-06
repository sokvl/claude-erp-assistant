import pytest

from app import cli

PASSWORD = "correct horse battery staple"


class Users:
    def __init__(self):
        self.documents = {}

    def insert_one(self, document):
        self.documents[document["_id"]] = document


@pytest.fixture
def users(monkeypatch):
    collection = Users()
    monkeypatch.setattr(cli, "get_database", lambda: {"users": collection})
    return collection


def _answers(monkeypatch, *answers):
    replies = iter(answers)
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: next(replies))


def test_main_create_user_prompts_twice_and_stores_the_account(monkeypatch, users, capsys):
    # Arrange
    _answers(monkeypatch, PASSWORD, PASSWORD)

    # Act
    code = cli.main(["create-user", "Anna", "--role", "admin"])

    # Assert
    assert (code, capsys.readouterr().out) == (0, "Created anna (admin)\n")
    assert users.documents["anna"]["role"] == "admin"


@pytest.mark.parametrize(
    ("answers", "message"),
    [
        ((PASSWORD, PASSWORD + "x"), "passwords do not match"),
        (("short", "short"), "Password must be"),
    ],
    ids=["mismatch", "too_short"],
)
def test_main_create_user_bad_password_exits_1_and_stores_nothing(monkeypatch, users, capsys, answers, message):
    # Arrange
    _answers(monkeypatch, *answers)

    # Act
    code = cli.main(["create-user", "anna", "--role", "manager"])

    # Assert
    assert code == 1
    assert message in capsys.readouterr().err
    assert users.documents == {}


def test_main_create_user_unknown_role_exits_2(users):
    # Arrange / Act / Assert: argparse rejects it before any password prompt
    with pytest.raises(SystemExit) as raised:
        cli.main(["create-user", "anna", "--role", "owner"])
    assert raised.value.code == 2
