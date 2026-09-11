"""Operator commands. Every destructive one is a report until told otherwise."""
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from graft.cli import cleanup_conversations, find_orphan_files, legacy_report
from graft.ingestion.storage import save_source
from graft.models import Bot, Conversation, Document, Message


@pytest.fixture
async def maker(db_engine):
    return async_sessionmaker(db_engine, expire_on_commit=False)


async def _bot(session, name="b"):
    bot = Bot(name=name, widget_key=f"wk_{uuid.uuid4().hex}")
    session.add(bot)
    await session.flush()
    return bot


# --- legacy report --------------------------------------------------------


async def test_a_healthy_instance_reports_nothing(maker):
    async with maker() as session:
        bot = await _bot(session)
        session.add(Document(
            bot_id=bot.id, filename="ok.md", mime_type="text/markdown", status="ready",
            storage_key=f"{bot.id}/x/source", embedding_fingerprint="f" * 64,
        ))
        await session.commit()
        assert await legacy_report(session) == []


async def test_documents_without_an_original_or_a_fingerprint_are_listed(maker):
    async with maker() as session:
        bot = await _bot(session, "Support")
        session.add_all([
            Document(bot_id=bot.id, filename="no-original.pdf", mime_type="application/pdf",
                     status="ready", chunk_count=4, embedding_fingerprint="f" * 64),
            Document(bot_id=bot.id, filename="no-fingerprint.md", mime_type="text/markdown",
                     status="ready", chunk_count=2, storage_key=f"{bot.id}/y/source"),
            # Failed and fingerprintless: never finished, so not a legacy row.
            Document(bot_id=bot.id, filename="never-worked.pdf", mime_type="application/pdf",
                     status="failed", chunk_count=0, storage_key=f"{bot.id}/z/source"),
        ])
        await session.commit()
        rows = await legacy_report(session)

    by_name = {row["filename"]: row for row in rows}
    assert by_name["no-original.pdf"]["missing_original"] is True
    assert by_name["no-original.pdf"]["missing_fingerprint"] is False
    assert by_name["no-fingerprint.md"]["missing_fingerprint"] is True
    assert by_name["no-fingerprint.md"]["bot"] == "Support"
    assert by_name["no-original.pdf"]["chunks"] == 4
    assert "never-worked.pdf" not in by_name


async def test_a_failed_document_is_not_legacy_data(maker):
    """It has no fingerprint because it never finished, which is a different problem."""
    async with maker() as session:
        bot = await _bot(session)
        session.add(Document(
            bot_id=bot.id, filename="scan.pdf", mime_type="application/pdf",
            status="failed", error="no_extractable_text", chunk_count=0,
            storage_key=f"{bot.id}/z/source",
        ))
        await session.commit()
        assert await legacy_report(session) == []


async def test_the_report_changes_nothing(maker):
    async with maker() as session:
        bot = await _bot(session)
        session.add(Document(bot_id=bot.id, filename="legacy.pdf",
                             mime_type="application/pdf", status="ready", chunk_count=7))
        await session.commit()
        await legacy_report(session)
    async with maker() as session:
        row = (await session.execute(select(Document))).scalars().one()
        # Still there, still ready, still holding its chunk count.
        assert (row.status, row.chunk_count) == ("ready", 7)


# --- conversation retention -----------------------------------------------


async def test_only_conversations_past_the_window_are_deleted(maker):
    async with maker() as session:
        bot = await _bot(session)
        old = Conversation(bot_id=bot.id, visitor_session="old",
                           started_at=datetime.now(UTC) - timedelta(days=45))
        recent = Conversation(bot_id=bot.id, visitor_session="recent",
                              started_at=datetime.now(UTC) - timedelta(days=3))
        session.add_all([old, recent])
        await session.flush()
        session.add(Message(conversation_id=old.id, role="user", content="hi",
                            status="completed"))
        await session.commit()
        old_id = old.id

        removed = await cleanup_conversations(session, days=30)

    assert removed == 1
    async with maker() as session:
        left = (await session.execute(select(Conversation))).scalars().all()
        assert [c.visitor_session for c in left] == ["recent"]
        # Messages follow their conversation rather than outliving it.
        messages = (await session.execute(
            select(Message).where(Message.conversation_id == old_id))).scalars().all()
        assert messages == []


async def test_deleting_nothing_is_not_an_error(maker):
    async with maker() as session:
        assert await cleanup_conversations(session, days=30) == 0


# --- orphan originals ------------------------------------------------------


async def test_a_directory_with_no_row_is_an_orphan(maker, tmp_path):
    bot_id, kept_id, orphan_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    kept_key = save_source(tmp_path, bot_id, kept_id, b"kept")
    save_source(tmp_path, bot_id, orphan_id, b"left behind")
    async with maker() as session:
        bot = await _bot(session)
        session.add(Document(bot_id=bot.id, filename="kept.md", mime_type="text/markdown",
                             status="ready", storage_key=kept_key))
        await session.commit()
        orphans = await find_orphan_files(session, tmp_path)

    assert [p.name for p in orphans] == [str(orphan_id)]
    # Reporting does not remove anything.
    assert (tmp_path / str(bot_id) / str(orphan_id)).is_dir()


async def test_nothing_is_an_orphan_when_every_file_has_its_row(maker, tmp_path):
    bot_id, document_id = uuid.uuid4(), uuid.uuid4()
    key = save_source(tmp_path, bot_id, document_id, b"x")
    async with maker() as session:
        bot = await _bot(session)
        session.add(Document(bot_id=bot.id, filename="a.md", mime_type="text/markdown",
                             status="ready", storage_key=key))
        await session.commit()
        assert await find_orphan_files(session, tmp_path) == []


async def test_a_missing_storage_root_is_not_a_crash(maker):
    async with maker() as session:
        assert await find_orphan_files(session, Path("/nonexistent-graft-volume")) == []
