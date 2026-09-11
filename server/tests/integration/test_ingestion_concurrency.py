"""Fencing: only the worker that holds the lease may publish a result.

arq (and any at-least-once queue) can run the same job twice. The run id in the
database — not the queue — decides whose work counts.
"""
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from graft.ingestion.jobs import (
    claim_document,
    fail_document,
    finish_document,
    heartbeat_document,
)
from graft.models import Bot, Chunk, Document

FINGERPRINT = "f" * 64


async def _bot_and_document(session, *, status="pending", fingerprint=None):
    bot = Bot(name="b", widget_key=f"wk_{uuid.uuid4().hex}")
    session.add(bot)
    await session.flush()
    doc = Document(
        bot_id=bot.id,
        filename="d.txt",
        mime_type="text/plain",
        status=status,
        storage_key=f"{bot.id}/x/source",
        embedding_fingerprint=fingerprint,
    )
    session.add(doc)
    await session.commit()
    return bot, doc


def _chunk(doc, bot, position=0, content="text"):
    return Chunk(
        document_id=doc.id,
        bot_id=bot.id,
        content=content,
        embedding=[0.1, 0.2],
        embedding_dim=2,
        position=position,
        chunk_metadata={},
    )


async def test_only_one_of_two_concurrent_claims_wins(db_engine):
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as setup:
        _, doc = await _bot_and_document(setup)

    now = datetime.now(UTC)
    async with maker() as a, maker() as b:
        first = await claim_document(a, doc.id, now)
        second = await claim_document(b, doc.id, now)
    assert (first is None) != (second is None)


async def test_an_expired_lease_can_be_reclaimed(db_engine):
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as setup:
        _, doc = await _bot_and_document(setup)
    now = datetime.now(UTC)
    async with maker() as session:
        first = await claim_document(session, doc.id, now, lease_seconds=60)
        assert first is not None
        # Same instant: the lease is still valid, so nobody else gets it.
        assert await claim_document(session, doc.id, now) is None
        later = now + timedelta(seconds=61)
        second = await claim_document(session, doc.id, later)
    assert second is not None and second != first


async def test_claims_stop_at_the_attempt_ceiling(db_engine):
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as setup:
        _, doc = await _bot_and_document(setup)
    async with maker() as session:
        now = datetime.now(UTC)
        for attempt in range(3):
            assert await claim_document(
                session, doc.id, now + timedelta(seconds=200 * attempt), max_attempts=3
            ) is not None
        assert await claim_document(
            session, doc.id, now + timedelta(seconds=1000), max_attempts=3
        ) is None


async def test_heartbeat_extends_only_the_owning_run(db_engine):
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as setup:
        _, doc = await _bot_and_document(setup)
    now = datetime.now(UTC)
    async with maker() as session:
        run_id = await claim_document(session, doc.id, now, lease_seconds=60)
        assert await heartbeat_document(session, doc.id, run_id, now + timedelta(seconds=30))
        assert not await heartbeat_document(session, doc.id, uuid.uuid4(), now)
        refreshed = await session.get(Document, doc.id)
        await session.refresh(refreshed)
        assert refreshed.lease_expires_at > now + timedelta(seconds=60)


async def test_finish_publishes_chunks_and_clears_the_lease(db_engine):
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as setup:
        bot, doc = await _bot_and_document(setup)
    async with maker() as session:
        run_id = await claim_document(session, doc.id, datetime.now(UTC))
        published = await finish_document(
            session, doc.id, run_id, FINGERPRINT, [_chunk(doc, bot)]
        )
    assert published
    async with maker() as session:
        row = await session.get(Document, doc.id)
        assert row.status == "ready"
        assert row.chunk_count == 1
        assert row.error is None
        assert row.lease_expires_at is None
        assert row.attempt_count == 0
        assert row.embedding_fingerprint == FINGERPRINT


async def test_a_stale_run_cannot_overwrite_a_newer_one(db_engine):
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as setup:
        bot, doc = await _bot_and_document(setup)
    now = datetime.now(UTC)
    async with maker() as session:
        stale_run = await claim_document(session, doc.id, now, lease_seconds=60)
        fresh_run = await claim_document(session, doc.id, now + timedelta(seconds=61))
        assert stale_run != fresh_run

        # The slow worker finally comes back with its result: it must be discarded.
        published = await finish_document(
            session, doc.id, stale_run, FINGERPRINT, [_chunk(doc, bot, content="stale")]
        )
        assert not published
        assert not await fail_document(session, doc.id, stale_run, "provider_timeout")

    async with maker() as session:
        assert (await session.get(Document, doc.id)).status == "processing"
        rows = (await session.execute(select(Chunk).where(Chunk.document_id == doc.id))
                ).scalars().all()
        assert rows == []


async def test_a_deleted_document_is_not_resurrected(db_engine):
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as setup:
        bot, doc = await _bot_and_document(setup)
    async with maker() as session:
        run_id = await claim_document(session, doc.id, datetime.now(UTC))
    async with maker() as session:
        await session.delete(await session.get(Document, doc.id))
        await session.commit()
    async with maker() as session:
        assert not await finish_document(
            session, doc.id, run_id, FINGERPRINT, [_chunk(doc, bot)]
        )
    async with maker() as session:
        rows = (await session.execute(select(Chunk))).scalars().all()
        assert all(r.document_id != doc.id for r in rows)


async def test_finish_refuses_a_fingerprint_that_no_longer_matches(db_engine):
    """The bot's embedding config changed mid-flight: the vectors are now foreign."""
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as setup:
        bot, doc = await _bot_and_document(setup)
    async with maker() as session:
        run_id = await claim_document(session, doc.id, datetime.now(UTC))
        assert not await finish_document(
            session, doc.id, run_id, FINGERPRINT, [_chunk(doc, bot)],
            expected_fingerprint="e" * 64,
        )
    async with maker() as session:
        assert (await session.get(Document, doc.id)).status != "ready"


async def test_fail_records_a_code_and_keeps_previous_chunks(db_engine):
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as setup:
        bot, doc = await _bot_and_document(setup)
        setup.add(_chunk(doc, bot, content="previous answer"))
        await setup.commit()
    async with maker() as session:
        run_id = await claim_document(session, doc.id, datetime.now(UTC))
        assert await fail_document(session, doc.id, run_id, "provider_auth")
    async with maker() as session:
        row = await session.get(Document, doc.id)
        assert row.status == "failed"
        assert row.error == "provider_auth"
        assert row.lease_expires_at is None
        rows = (await session.execute(select(Chunk).where(Chunk.document_id == doc.id))
                ).scalars().all()
        # Old chunks stay on disk; `status` is what keeps them out of retrieval.
        assert [r.content for r in rows] == ["previous answer"]
