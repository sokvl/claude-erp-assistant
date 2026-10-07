from datetime import UTC, datetime

import pytest
from memory_collection import MemoryCollection

from app import cli
from app.auth.api_keys import api_key_owner
from app.auth.roles import Role
from app.auth.users import create_user

PASSWORD = "correct horse battery staple"


@pytest.fixture
def db(monkeypatch):
    database = {"users": MemoryCollection(), "api_keys": MemoryCollection()}
    monkeypatch.setattr(cli, "get_database", lambda: database)
    return database


def _answers(monkeypatch, *answers):
    replies = iter(answers)
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: next(replies))


def _issue(capsys, *extra):
    code = cli.main(["issue-api-key", "anna", "--name", "evals", *extra])
    return code, capsys.readouterr().out.splitlines()


def test_main_create_user_prompts_twice_and_stores_the_account(monkeypatch, db, capsys):
    # Arrange
    _answers(monkeypatch, PASSWORD, PASSWORD)

    # Act
    code = cli.main(["create-user", "Anna", "--role", "admin"])

    # Assert
    assert (code, capsys.readouterr().out) == (0, "Created anna (admin)\n")
    assert db["users"].documents["anna"]["role"] == "admin"


@pytest.mark.parametrize(
    ("answers", "message"),
    [
        ((PASSWORD, PASSWORD + "x"), "passwords do not match"),
        (("short", "short"), "Password must be"),
    ],
    ids=["mismatch", "too_short"],
)
def test_main_create_user_bad_password_exits_1_and_stores_nothing(monkeypatch, db, capsys, answers, message):
    # Arrange
    _answers(monkeypatch, *answers)

    # Act
    code = cli.main(["create-user", "anna", "--role", "manager"])

    # Assert
    assert code == 1
    assert message in capsys.readouterr().err
    assert db["users"].documents == {}


def test_main_create_user_unknown_role_exits_2(db):
    # Arrange / Act / Assert: argparse rejects it before any password prompt
    with pytest.raises(SystemExit) as raised:
        cli.main(["create-user", "anna", "--role", "owner"])
    assert raised.value.code == 2


def test_main_issue_api_key_prints_a_working_key_and_its_prefix(db, capsys):
    # Arrange
    create_user(db["users"], "anna", PASSWORD, Role.MANAGER)

    # Act
    code, (key, note) = _issue(capsys, "--days", "30")

    # Assert
    assert code == 0
    assert api_key_owner(db["api_keys"], key, datetime.now(UTC)) == "anna"
    assert note.startswith(f"prefix {key.split('_')[1]}, valid 30 days")


@pytest.mark.parametrize(
    ("create", "extra", "message"),
    [(False, (), "no user 'anna'"), (True, ("--days", "0"), "An API key lives")],
    ids=["unknown_user", "zero_days"],
)
def test_main_issue_api_key_rejected_exits_1_and_stores_nothing(db, capsys, create, extra, message):
    # Arrange
    if create:
        create_user(db["users"], "anna", PASSWORD, Role.MANAGER)

    # Act
    code = cli.main(["issue-api-key", "anna", "--name", "evals", *extra])

    # Assert
    assert code == 1
    assert message in capsys.readouterr().err
    assert db["api_keys"].documents == {}


def test_main_revoke_api_key_by_its_prefix_stops_the_key(db, capsys):
    # Arrange
    create_user(db["users"], "anna", PASSWORD, Role.MANAGER)
    _, (key, _) = _issue(capsys)

    # Act
    code = cli.main(["revoke-api-key", "anna", key.split("_")[1]])

    # Assert
    assert (code, capsys.readouterr().out) == (0, f"Revoked {key.split('_')[1]}\n")
    assert api_key_owner(db["api_keys"], key, datetime.now(UTC)) is None


def test_main_revoke_api_key_unknown_prefix_exits_1(db, capsys):
    # Arrange / Act
    code = cli.main(["revoke-api-key", "anna", "00000000"])

    # Assert
    assert code == 1
    assert "no active key" in capsys.readouterr().err
