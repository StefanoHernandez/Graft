"""Worker behaviour against a real Postgres and a real Redis.

The queue is a hint; the database is the work list. Every test here is about
what happens when the hint is lost, duplicated, or arrives twice.
"""
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from arq import Retry
from arq.connections import ArqRedis, RedisSettings, create_pool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker
from testcontainers.community.redis import RedisContainer

from graft.config import get_settings
from graft.ingestion.queue import enqueue_document
from graft.ingestion.storage import save_source
from graft.ingestion.worker import dispatch_pending, ingest_job
from graft.models import Bot, Chunk, Document
from graft.providers.base import ProviderError

EMBEDDING_CONFIG = {"provider": "openai_compatible", "model": "m", "api_key": None}


class _FakeEmbedder:
    def __init__(self, dim=4):
        self.dim = dim
        self.calls = 0

    async def embed(self, texts, *, model):
        self.calls += 1
        return [[0.5] * self.dim for _ in texts]

    async def aclose(self):
        return None


class _FailingEmbedder:
    def __init__(self, exc):
        self._exc = exc
        self.calls = 0

    async def embed(self, texts, *, model):
        self.calls += 1
        raise self._exc

    async def aclose(self):
        return None


@pytest.fixture(scope="module")
def redis_container():
    with RedisContainer("redis:7-alpine") as container:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(6379)
        container.dsn = f"redis://{host}:{port}"
        yield container


@pytest_asyncio.fixture
async def arq_redis(redis_container) -> ArqRedis:
    pool = await create_pool(RedisSettings.from_dsn(redis_container.dsn))
    await pool.flushall()
    yield pool
    await pool.aclose()


@pytest_asyncio.fixture
async def maker(db_engine):
    return async_sessionmaker(db_engine, expire_on_commit=False)


async def _document(maker, data=b"A paragraph.\n\nAnother paragraph.", status="pending"):
    storage_root = get_settings().storage_root
    async with maker() as session:
        bot = Bot(name="b", widget_key=f"wk_{uuid.uuid4().hex}",
                  embedding_config=EMBEDDING_CONFIG)
        session.add(bot)
        await session.flush()
        doc = Document(bot_id=bot.id, filename="d.txt", mime_type="text/plain", status=status)
        session.add(doc)
        await session.flush()
        doc.storage_key = save_source(storage_root, bot.id, doc.id, data)
        await session.commit()
        return doc


def _ctx(redis, maker=None, job_try=1):
    return {"redis": redis, "job_try": job_try, "sessionmaker": maker}


def _use_embedder(monkeypatch, embedder):
    from graft.ingestion import worker

    monkeypatch.setattr(worker, "build_embedder", lambda config, **kw: embedder)


# --- the queue carries ids only ----------------------------------------------


async def test_enqueue_sends_an_id_and_nothing_else(arq_redis, maker):
    doc = await _document(maker)
    job = await enqueue_document(arq_redis, doc.id)
    assert job is not None
    info = await job.info()
    assert info.args == (str(doc.id),)
    assert b"paragraph" not in str(info.args).encode()


async def test_a_duplicate_enqueue_is_harmless(arq_redis, maker):
    doc = await _document(maker)
    first = await enqueue_document(arq_redis, doc.id)
    second = await enqueue_document(arq_redis, doc.id)
    assert first is not None
    # Same stable job id: arq refuses the duplicate instead of queueing twice.
    assert second is None


# --- the job -----------------------------------------------------------------


async def test_job_ingests_the_document(arq_redis, maker, monkeypatch):
    doc = await _document(maker)
    embedder = _FakeEmbedder()
    _use_embedder(monkeypatch, embedder)
    count = await ingest_job(_ctx(arq_redis, maker), str(doc.id))
    # Both short paragraphs fit one chunk: packing is the point.
    assert count == 1
    async with maker() as session:
        row = await session.get(Document, doc.id)
        assert row.status == "ready"
        assert row.chunk_count == 1
        assert row.embedding_fingerprint


async def test_a_repeated_job_after_a_lost_ack_does_nothing(arq_redis, maker, monkeypatch):
    """Crash between the commit and the ack: the job runs again and must exit."""
    doc = await _document(maker)
    embedder = _FakeEmbedder()
    _use_embedder(monkeypatch, embedder)
    first = await ingest_job(_ctx(arq_redis, maker), str(doc.id))
    calls_after_first = embedder.calls
    assert await ingest_job(_ctx(arq_redis, maker), str(doc.id)) is None
    assert embedder.calls == calls_after_first
    async with maker() as session:
        chunks = (await session.execute(
            select(Chunk).where(Chunk.document_id == doc.id))).scalars().all()
    # A replayed job must not double the corpus.
    assert len(chunks) == first


async def test_a_deleted_document_is_not_an_error(arq_redis, maker, monkeypatch):
    doc = await _document(maker)
    _use_embedder(monkeypatch, _FakeEmbedder())
    async with maker() as session:
        await session.delete(await session.get(Document, doc.id))
        await session.commit()
    assert await ingest_job(_ctx(arq_redis, maker), str(doc.id)) is None


async def test_a_permanent_provider_error_fails_the_document_at_once(
    arq_redis, maker, monkeypatch
):
    doc = await _document(maker)
    _use_embedder(monkeypatch, _FailingEmbedder(ProviderError("provider_auth")))
    with pytest.raises(ProviderError):
        await ingest_job(_ctx(arq_redis, maker), str(doc.id))
    async with maker() as session:
        row = await session.get(Document, doc.id)
        assert row.status == "failed"
        assert row.error == "provider_auth"


async def test_a_transient_error_is_retried_with_backoff(arq_redis, maker, monkeypatch):
    doc = await _document(maker)
    _use_embedder(
        monkeypatch, _FailingEmbedder(ProviderError("provider_rate_limit", retryable=True))
    )
    with pytest.raises(Retry) as excinfo:
        await ingest_job(_ctx(arq_redis, maker, job_try=1), str(doc.id))
    assert excinfo.value.defer_score == 10_000  # arq stores the defer in milliseconds
    async with maker() as session:
        row = await session.get(Document, doc.id)
        # Back to claimable, but the attempt is still counted.
        assert row.status == "pending"
        assert row.error is None
        assert row.attempt_count == 1

    with pytest.raises(Retry) as second:
        await ingest_job(_ctx(arq_redis, maker, job_try=2), str(doc.id))
    assert second.value.defer_score == 30_000


async def test_attempts_run_out_and_the_document_ends_failed(
    arq_redis, maker, monkeypatch
):
    doc = await _document(maker)
    _use_embedder(
        monkeypatch, _FailingEmbedder(ProviderError("provider_timeout", retryable=True))
    )
    for attempt in (1, 2, 3):
        with pytest.raises((Retry, ProviderError)):
            await ingest_job(_ctx(arq_redis, maker, job_try=attempt), str(doc.id))
    # The fourth pickup cannot claim any more; the dispatcher must not leave it
    # sitting in pending forever.
    assert await ingest_job(_ctx(arq_redis, maker, job_try=4), str(doc.id)) is None
    await dispatch_pending(_ctx(arq_redis, maker))
    async with maker() as session:
        row = await session.get(Document, doc.id)
        assert row.status == "failed"
        assert row.error == "attempts_exhausted"


# --- the dispatcher ----------------------------------------------------------


async def test_dispatcher_picks_up_a_document_redis_never_heard_about(
    arq_redis, maker
):
    """Redis was down when the upload committed. The row is still the work list."""
    doc = await _document(maker)
    queued = await dispatch_pending(_ctx(arq_redis, maker))
    assert str(doc.id) in queued


async def test_dispatcher_reclaims_an_expired_lease(arq_redis, maker):
    doc = await _document(maker)
    async with maker() as session:
        row = await session.get(Document, doc.id)
        row.status = "processing"
        row.ingestion_run_id = uuid.uuid4()
        row.lease_expires_at = datetime.now(UTC) - timedelta(minutes=5)
        await session.commit()
    queued = await dispatch_pending(_ctx(arq_redis, maker))
    assert str(doc.id) in queued


async def test_dispatcher_leaves_a_live_lease_alone(arq_redis, maker):
    doc = await _document(maker)
    async with maker() as session:
        row = await session.get(Document, doc.id)
        row.status = "processing"
        row.ingestion_run_id = uuid.uuid4()
        row.lease_expires_at = datetime.now(UTC) + timedelta(minutes=5)
        await session.commit()
    assert str(doc.id) not in await dispatch_pending(_ctx(arq_redis, maker))


async def test_dispatcher_ignores_ready_documents(arq_redis, maker):
    await _document(maker, status="ready")
    assert await dispatch_pending(_ctx(arq_redis, maker)) == []


async def test_dispatch_survives_a_redis_restart(redis_container, maker):
    """Redis losing its queue must not lose the work: the sweep rebuilds it."""
    doc = await _document(maker)
    pool = await create_pool(RedisSettings.from_dsn(redis_container.dsn))
    await pool.flushall()  # as if Redis had come back empty
    queued = await dispatch_pending({"redis": pool, "sessionmaker": maker})
    await pool.aclose()
    assert str(doc.id) in queued


async def test_documents_of_every_bot_are_swept(arq_redis, maker):
    first = await _document(maker)
    second = await _document(maker)
    queued = await dispatch_pending(_ctx(arq_redis, maker))
    assert {str(first.id), str(second.id)} <= set(queued)


async def test_pending_rows_are_found_by_status(db_engine, maker, arq_redis):
    await _document(maker)
    async with maker() as session:
        rows = (await session.execute(select(Document).where(Document.status == "pending"))
                ).scalars().all()
    assert len(rows) == 1
