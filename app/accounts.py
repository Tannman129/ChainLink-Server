"""Local account provisioning: python -m app.accounts USERNAME --role ROLE."""

import argparse
import sys
from getpass import getpass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import create_account
from app.database import get_engine


def main():
    parser = argparse.ArgumentParser(
        description="Create a local ChainLink account; password is prompted securely."
    )
    parser.add_argument("username")
    parser.add_argument("--role", choices=["player", "administrator"], default="player")
    args = parser.parse_args()
    if not sys.stdin.isatty():
        parser.exit(1, "Use an interactive terminal to provision accounts securely.\n")
    password = getpass("Password (12–256 characters): ")
    if password != getpass("Confirm password: "):
        parser.exit(1, "Passwords do not match.\n")
    try:
        with Session(get_engine()) as db:
            create_account(db, args.username, password, args.role)
    except ValueError as error:
        parser.exit(1, str(error) + "\n")
    except IntegrityError:
        parser.exit(1, "Username already exists. No account created.\n")
    print("Account created.")


if __name__ == "__main__":
    main()
