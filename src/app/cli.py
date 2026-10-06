import argparse
import getpass
import sys

from app.auth.roles import Role
from app.auth.users import USER_COLLECTION, create_user
from app.db import get_database


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="Bootstrap accounts.")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create-user", help="create an account; prompts for the password")
    create.add_argument("username")
    create.add_argument("--role", type=Role, choices=list(Role), required=True)
    args = parser.parse_args(argv)

    password = getpass.getpass("Password: ")
    if password != getpass.getpass("Repeat password: "):
        print("error: passwords do not match", file=sys.stderr)
        return 1
    try:
        username = create_user(get_database()[USER_COLLECTION], args.username, password, args.role)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Created {username} ({args.role})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
