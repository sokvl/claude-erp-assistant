import argparse
import getpass
import sys
from datetime import UTC, datetime

from app.auth.api_keys import API_KEY_COLLECTION, issue_api_key, revoke_api_key
from app.auth.roles import Role
from app.auth.users import USER_COLLECTION, create_user, find_user
from app.db import get_database
from app.limits import API_KEY_MAX_DAYS


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="Bootstrap accounts and API keys.")
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser("create-user", help="create an account; prompts for the password")
    create.add_argument("username")
    create.add_argument("--role", type=Role, choices=list(Role), required=True)

    issue = commands.add_parser("issue-api-key", help="issue a key that acts as this account; printed once")
    issue.add_argument("username")
    issue.add_argument("--name", required=True, help="what the key is for, e.g. evals")
    issue.add_argument("--days", type=int, default=API_KEY_MAX_DAYS)

    revoke = commands.add_parser("revoke-api-key", help="revoke a key by the prefix printed when it was issued")
    revoke.add_argument("username")
    revoke.add_argument("prefix")
    return parser


def _create_user(args: argparse.Namespace) -> str:
    password = getpass.getpass("Password: ")
    if password != getpass.getpass("Repeat password: "):
        raise ValueError("passwords do not match")
    username = create_user(get_database()[USER_COLLECTION], args.username, password, args.role)
    return f"Created {username} ({args.role})"


def _issue_api_key(args: argparse.Namespace) -> str:
    db = get_database()
    user = find_user(db[USER_COLLECTION], args.username)
    if user is None:
        raise ValueError(f"no user {args.username!r}")
    key = issue_api_key(db[API_KEY_COLLECTION], user["_id"], args.name, datetime.now(UTC), args.days)
    return f"{key}\nprefix {key.split('_')[1]}, valid {args.days} days; this is the only time the key is shown"


def _revoke_api_key(args: argparse.Namespace) -> str:
    if not revoke_api_key(get_database()[API_KEY_COLLECTION], args.username, args.prefix, datetime.now(UTC)):
        raise ValueError(f"no active key {args.prefix!r} for {args.username!r}")
    return f"Revoked {args.prefix}"


COMMANDS = {"create-user": _create_user, "issue-api-key": _issue_api_key, "revoke-api-key": _revoke_api_key}


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        print(COMMANDS[args.command](args))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
