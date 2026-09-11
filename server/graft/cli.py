"""Operator commands. No account is ever created over HTTP."""
from __future__ import annotations

import argparse
import asyncio
import getpass
import sys

from fastapi_users.password import PasswordHelper
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_sessionmaker
from .models import User

# Any constant works; it only has to be the same in every process running this
# bootstrap. Postgres advisory locks are per-database and released on commit.
_BOOTSTRAP_LOCK = 8_271_001


async def create_admin(
    session: AsyncSession, email: str, password: str, *, role: str = "owner"
) -> User:
    """Create the operator account.

    Two operators running this at the same moment must not end up with two
    owners, so the check and the insert sit behind one transaction-scoped
    advisory lock rather than a read followed by a hopeful write.
    """
    await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _BOOTSTRAP_LOCK})
    if role == "owner":
        existing = await session.scalar(
            select(func.count()).select_from(User).where(User.role == "owner")
        )
        if existing:
            raise ValueError("an owner already exists")

    user = User(
        email=email,
        hashed_password=PasswordHelper().hash(password),
        is_active=True,
        is_superuser=role == "owner",
        is_verified=True,
        role=role,
    )
    session.add(user)
    await session.commit()
    return user


async def _create_admin_command(email: str, role: str) -> int:
    password = getpass.getpass("Password: ")
    if password != getpass.getpass("Repeat password: "):
        print("passwords do not match", file=sys.stderr)
        return 2
    if len(password) < 12:
        print("password must be at least 12 characters", file=sys.stderr)
        return 2
    async with get_sessionmaker()() as session:
        try:
            await create_admin(session, email, password, role=role)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
    print(f"created {role}: {email}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="graft")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create-admin", help="create the operator account")
    create.add_argument("email")
    create.add_argument("--role", default="owner", choices=["owner", "editor", "viewer"])
    args = parser.parse_args(argv)
    if args.command == "create-admin":
        return asyncio.run(_create_admin_command(args.email, args.role))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
