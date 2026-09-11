"""Operator commands. No account is ever created over HTTP."""
from __future__ import annotations

import argparse
import asyncio
import getpass
import shutil
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi_users.password import PasswordHelper
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .db import get_sessionmaker
from .models import Bot, Conversation, Document, User

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


async def legacy_report(session: AsyncSession) -> list[dict]:
    """List documents the current pipeline can no longer use.

    Two kinds, both from before the lifecycle migration: no stored original (it
    was never kept, and cannot be rebuilt from the chunks), and a *ready*
    document with no embedding fingerprint (its chunks exist but retrieval skips
    them, because their vectors belong to an unknown model).

    A failed document without a fingerprint is not legacy data — it simply never
    finished — so it is not listed here. This reports; it never invents a hash
    and never deletes a chunk.
    """
    rows = (
        await session.execute(
            select(Document.id, Document.filename, Document.status,
                   Document.chunk_count, Document.storage_key,
                   Document.embedding_fingerprint, Bot.name)
            .join(Bot, Bot.id == Document.bot_id)
            .where(
                (Document.storage_key.is_(None))
                | (
                    Document.embedding_fingerprint.is_(None)
                    & (Document.status == "ready")
                )
            )
            .order_by(Bot.name, Document.filename)
        )
    ).all()
    return [
        {
            "id": str(row.id),
            "bot": row.name,
            "filename": row.filename,
            "status": row.status,
            "chunks": row.chunk_count,
            "missing_original": row.storage_key is None,
            "missing_fingerprint": row.embedding_fingerprint is None,
        }
        for row in rows
    ]


async def cleanup_conversations(session: AsyncSession, days: int) -> int:
    """Delete conversations older than `days`. Messages follow by cascade."""
    cutoff = datetime.now(UTC) - timedelta(days=days)
    result = await session.execute(
        delete(Conversation).where(Conversation.started_at < cutoff)
    )
    await session.commit()
    return result.rowcount or 0


async def find_orphan_files(session: AsyncSession, root: Path) -> list[Path]:
    """Directories under the storage root with no document row pointing at them.

    They appear when a delete removed the row and the file cleanup failed after
    it — the deliberate order, because a stray file is a chore and a stray row is
    a live document.
    """
    if not root.is_dir():
        return []
    known = {
        key for (key,) in await session.execute(
            select(Document.storage_key).where(Document.storage_key.is_not(None))
        )
    }
    live_dirs = {(root / key).parent.resolve() for key in known}
    orphans = []
    for bot_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        for document_dir in sorted(p for p in bot_dir.iterdir() if p.is_dir()):
            if document_dir.resolve() not in live_dirs:
                orphans.append(document_dir)
    return orphans


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


async def _legacy_report_command() -> int:
    async with get_sessionmaker()() as session:
        rows = await legacy_report(session)
    if not rows:
        print("No legacy documents: every document has an original and a fingerprint.")
        return 0
    print(f"{len(rows)} document(s) the current pipeline cannot use:\n")
    for row in rows:
        missing = []
        if row["missing_original"]:
            missing.append("no stored original")
        if row["missing_fingerprint"]:
            missing.append("no embedding fingerprint")
        print(f"  {row['bot']} / {row['filename']}  [{row['status']}, "
              f"{row['chunks']} chunks]  {', '.join(missing)}")
    print(
        "\nNothing was changed. These documents stay searchable only if their bot is\n"
        "left alone; to bring them back, upload the files again to a bot whose\n"
        "embedding configuration is the one you want to keep. The originals cannot be\n"
        "reconstructed from the stored chunks."
    )
    return 0


async def _cleanup_conversations_command(days: int, apply_it: bool) -> int:
    async with get_sessionmaker()() as session:
        cutoff = datetime.now(UTC) - timedelta(days=days)
        doomed = await session.scalar(
            select(func.count()).select_from(Conversation)
            .where(Conversation.started_at < cutoff)
        )
        if not apply_it:
            print(f"{doomed or 0} conversation(s) started before {cutoff:%Y-%m-%d} "
                  f"would be deleted. Re-run with --apply to delete them.")
            return 0
        removed = await cleanup_conversations(session, days)
    print(f"Deleted {removed} conversation(s) and their messages.")
    return 0


async def _cleanup_orphan_files_command(apply_it: bool) -> int:
    root = get_settings().storage_root
    async with get_sessionmaker()() as session:
        orphans = await find_orphan_files(session, root)
    if not orphans:
        print(f"No orphan directories under {root}.")
        return 0
    for path in orphans:
        print(path)
    if not apply_it:
        print(f"\n{len(orphans)} orphan director(ies). Nothing was deleted; "
              "re-run with --apply to remove them.")
        return 0
    for path in orphans:
        shutil.rmtree(path, ignore_errors=True)
    print(f"\nDeleted {len(orphans)} orphan director(ies).")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="graft")
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser("create-admin", help="create the operator account")
    create.add_argument("email")
    create.add_argument("--role", default="owner", choices=["owner", "editor", "viewer"])

    commands.add_parser(
        "legacy-report",
        help="list documents with no stored original or no embedding fingerprint",
    )

    conversations = commands.add_parser(
        "cleanup-conversations", help="delete conversations older than N days"
    )
    conversations.add_argument("--days", type=int, default=30)
    conversations.add_argument("--apply", action="store_true",
                               help="actually delete; without it, only report")

    orphans = commands.add_parser(
        "cleanup-orphan-files", help="find stored originals with no document row"
    )
    orphans.add_argument("--apply", action="store_true",
                         help="actually delete; without it, only list")

    args = parser.parse_args(argv)
    if args.command == "create-admin":
        return asyncio.run(_create_admin_command(args.email, args.role))
    if args.command == "legacy-report":
        return asyncio.run(_legacy_report_command())
    if args.command == "cleanup-conversations":
        return asyncio.run(_cleanup_conversations_command(args.days, args.apply))
    if args.command == "cleanup-orphan-files":
        return asyncio.run(_cleanup_orphan_files_command(args.apply))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
