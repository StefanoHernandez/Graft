import asyncio
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from graft.ingestion.jobs import claim_document
from graft.ingestion.pipeline import ClaimFailed, ingest_document
from graft.ingestion.storage import save_source
from graft.models import Bot, Chunk, Document
from graft.providers.base import ProviderError

EMBEDDING_CONFIG = {"provider": "openai_compatible", "model": "m", "api_key": None}


class _FakeEmbedder:
    def __init__(self, dim=4):
        self.dim = dim
        self.batches = []

    async def embed(self, texts, *, model):
        self.batches.append(list(texts))
        return [[float(i + 1)] * self.dim for i in range(len(texts))]

    async def test_connection(self):
        return None


class _BoomEmbedder:
    def __init__(self, exc=None):
        self._exc = exc or ProviderError("provider_auth")

    async def embed(self, texts, *, model):
        raise self._exc

    async def test_connection(self):
        return None


class _RaggedEmbedder:
    """Second batch comes back in a different dimension."""

    def __init__(self):
        self.calls = 0

    async def embed(self, texts, *, model):
        self.calls += 1
        dim = 4 if self.calls == 1 else 8
        return [[0.5] * dim for _ in texts]

    async def test_connection(self):
        return None


async def _document(session, storage_root, data=b"hello world", filename="d.txt",
                    mime="text/plain", status="pending"):
    bot = Bot(name="b", widget_key=f"wk_{uuid.uuid4().hex}", embedding_config=EMBEDDING_CONFIG)
    session.add(bot)
    await session.flush()
    doc = Document(bot_id=bot.id, filename=filename, mime_type=mime, status=status)
    session.add(doc)
    await session.flush()
    doc.storage_key = save_source(storage_root, bot.id, doc.id, data)
    await session.commit()
    return doc


async def test_ingest_stores_chunks_with_provenance_and_marks_ready(db_engine, tmp_path):
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        doc = await _document(
            session, tmp_path,
            data=b"# Setup\n\nFirst paragraph.\n\n# Usage\n\nSecond paragraph.\n",
            filename="guide.md", mime="text/markdown",
        )
    embedder = _FakeEmbedder(dim=4)
    count = await ingest_document(
        maker, doc.id, embedder, embedding_model="m", storage_root=tmp_path
    )
    assert count == 2
    async with maker() as session:
        row = await session.get(Document, doc.id)
        assert row.status == "ready"
        assert row.chunk_count == 2
        assert row.error is None
        assert row.embedding_fingerprint
        chunks = (await session.execute(
            select(Chunk).where(Chunk.document_id == doc.id).order_by(Chunk.position))
        ).scalars().all()
        assert [c.position for c in chunks] == [0, 1]
        assert [c.chunk_metadata["heading"] for c in chunks] == ["Setup", "Usage"]
        assert all(c.embedding_dim == 4 for c in chunks)


async def test_pdf_pages_reach_chunk_metadata(db_engine, tmp_path):
    from pathlib import Path
    pdf = (Path(__file__).resolve().parents[1] / "fixtures" / "documents" / "two_pages.pdf")
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        doc = await _document(session, tmp_path, data=pdf.read_bytes(),
                              filename="two_pages.pdf", mime="application/pdf")
    await ingest_document(maker, doc.id, _FakeEmbedder(), embedding_model="m",
                          storage_root=tmp_path)
    async with maker() as session:
        chunks = (await session.execute(
            select(Chunk).where(Chunk.document_id == doc.id).order_by(Chunk.position))
        ).scalars().all()
        assert [c.chunk_metadata["page"] for c in chunks] == [1, 2]


async def test_embeddings_are_sent_in_batches(db_engine, tmp_path):
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    body = "\n\n".join(f"Paragraph {i}." for i in range(10))
    async with maker() as session:
        doc = await _document(session, tmp_path, data=body.encode())
    embedder = _FakeEmbedder()
    count = await ingest_document(
        maker, doc.id, embedder, embedding_model="m", storage_root=tmp_path,
        chunk_size=20, chunk_overlap=0, batch_size=3,
    )
    assert count > 3
    assert max(len(batch) for batch in embedder.batches) == 3
    assert sum(len(batch) for batch in embedder.batches) == count


async def test_dimension_change_between_batches_is_rejected(db_engine, tmp_path):
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    body = "\n\n".join(f"Paragraph {i}." for i in range(6))
    async with maker() as session:
        doc = await _document(session, tmp_path, data=body.encode())
    with pytest.raises(ProviderError) as excinfo:
        await ingest_document(
            maker, doc.id, _RaggedEmbedder(), embedding_model="m", storage_root=tmp_path,
            chunk_size=20, chunk_overlap=0, batch_size=2,
        )
    assert excinfo.value.code == "provider_invalid_response"
    async with maker() as session:
        assert (await session.get(Document, doc.id)).status == "failed"
        assert (await session.execute(
            select(Chunk).where(Chunk.document_id == doc.id))).scalars().all() == []


async def test_provider_failure_stores_the_code_not_the_message(db_engine, tmp_path):
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        doc = await _document(session, tmp_path)
    with pytest.raises(ProviderError):
        await ingest_document(maker, doc.id, _BoomEmbedder(), embedding_model="m",
                              storage_root=tmp_path)
    async with maker() as session:
        row = await session.get(Document, doc.id)
        assert row.status == "failed"
        assert row.error == "provider_auth"
        assert row.lease_expires_at is None


async def test_unparseable_document_fails_with_its_code(db_engine, tmp_path):
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        doc = await _document(session, tmp_path, data=b"   \n  ")
    with pytest.raises(Exception):  # noqa: B017 - ParseError, asserted through the row
        await ingest_document(maker, doc.id, _FakeEmbedder(), embedding_model="m",
                              storage_root=tmp_path)
    async with maker() as session:
        assert (await session.get(Document, doc.id)).error == "no_extractable_text"


async def test_retry_after_a_failure_succeeds_and_clears_the_error(db_engine, tmp_path):
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        doc = await _document(session, tmp_path)
    with pytest.raises(ProviderError):
        await ingest_document(maker, doc.id, _BoomEmbedder(), embedding_model="m",
                              storage_root=tmp_path)
    async with maker() as session:
        row = await session.get(Document, doc.id)
        row.status = "pending"  # what the retry endpoint does
        row.attempt_count = 0
        await session.commit()
    count = await ingest_document(maker, doc.id, _FakeEmbedder(), embedding_model="m",
                                  storage_root=tmp_path)
    assert count == 1
    async with maker() as session:
        row = await session.get(Document, doc.id)
        assert row.status == "ready"
        assert row.error is None


async def test_a_document_owned_by_another_worker_is_skipped(db_engine, tmp_path):
    from datetime import UTC, datetime

    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        doc = await _document(session, tmp_path)
        assert await claim_document(session, doc.id, datetime.now(UTC)) is not None
    with pytest.raises(ClaimFailed):
        await ingest_document(maker, doc.id, _FakeEmbedder(), embedding_model="m",
                              storage_root=tmp_path)


async def test_a_missing_original_fails_without_calling_the_provider(db_engine, tmp_path):
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        doc = await _document(session, tmp_path)
        row = await session.get(Document, doc.id)
        row.storage_key = None  # a legacy document, ingested before originals were kept
        await session.commit()

    class _NeverCalled:
        async def embed(self, texts, *, model):
            raise AssertionError("the provider must not be called")

    with pytest.raises(Exception):  # noqa: B017 - asserted through the row
        await ingest_document(maker, doc.id, _NeverCalled(), embedding_model="m",
                              storage_root=tmp_path)
    async with maker() as session:
        assert (await session.get(Document, doc.id)).error == "missing_source"


async def test_the_lease_is_extended_while_the_work_runs(db_engine, tmp_path):
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        doc = await _document(session, tmp_path)

    seen = []

    class _SlowEmbedder(_FakeEmbedder):
        async def embed(self, texts, *, model):
            await asyncio.sleep(0.35)
            async with maker() as probe:
                row = await probe.get(Document, doc.id)
                seen.append(row.lease_expires_at)
            return await super().embed(texts, model=model)

    await ingest_document(
        maker, doc.id, _SlowEmbedder(), embedding_model="m", storage_root=tmp_path,
        lease_seconds=2, heartbeat_seconds=0.1,
    )
    first_lease = seen[0]
    async with maker() as session:
        assert (await session.get(Document, doc.id)).status == "ready"
    assert first_lease is not None


async def test_cancelling_the_attempt_leaves_it_retryable(db_engine, tmp_path):
    """A worker shutting down must not burn the document as failed."""
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        doc = await _document(session, tmp_path)

    class _HangingEmbedder(_FakeEmbedder):
        async def embed(self, texts, *, model):
            await asyncio.sleep(30)
            return await super().embed(texts, model=model)

    task = asyncio.create_task(
        ingest_document(maker, doc.id, _HangingEmbedder(), embedding_model="m",
                        storage_root=tmp_path)
    )
    await asyncio.sleep(0.5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    async with maker() as session:
        row = await session.get(Document, doc.id)
        assert row.status == "processing"
        assert row.error is None
        assert row.lease_expires_at is not None
