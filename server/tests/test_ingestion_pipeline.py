import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from graft.ingestion.pipeline import ingest_document
from graft.models import Bot, Chunk, Document


class _FakeEmbedder:
    def __init__(self, dim=4):
        self.dim = dim
        self.calls = []

    async def embed(self, texts, *, model):
        self.calls.append((list(texts), model))
        return [[float(i)] * self.dim for i in range(len(texts))]

    async def test_connection(self):
        return None


class _BoomEmbedder:
    async def embed(self, texts, *, model):
        raise RuntimeError("embed boom")

    async def test_connection(self):
        return None


async def _make_doc(session, mime="text/plain", filename="d.txt"):
    bot = Bot(name="b", widget_key=f"wk_{uuid.uuid4().hex}")
    session.add(bot)
    await session.flush()
    doc = Document(bot_id=bot.id, filename=filename, mime_type=mime)
    session.add(doc)
    await session.commit()
    return doc


async def test_ingest_stores_chunks_and_marks_ready(db_engine):
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        doc = await _make_doc(session)
        emb = _FakeEmbedder(dim=4)
        n = await ingest_document(
            session, doc, ("abcdefghij" * 300).encode(), emb,
            embedding_model="m", chunk_size=1000, chunk_overlap=200)
        assert n == 4
        assert doc.status == "ready"
        assert doc.chunk_count == 4
        assert emb.calls[0][1] == "m"
        rows = (await session.execute(
            select(Chunk).where(Chunk.document_id == doc.id).order_by(Chunk.position))
        ).scalars().all()
        assert [r.position for r in rows] == [0, 1, 2, 3]
        assert all(r.embedding_dim == 4 for r in rows)
        assert all(r.bot_id == doc.bot_id for r in rows)


async def test_ingest_empty_document_marks_ready_zero(db_engine):
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        doc = await _make_doc(session)
        n = await ingest_document(session, doc, b"   \n  ", _FakeEmbedder(),
                                  embedding_model="m")
        assert n == 0
        assert doc.status == "ready"
        assert doc.chunk_count == 0


async def test_ingest_failure_marks_failed_and_reraises(db_engine):
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        doc = await _make_doc(session)
        with pytest.raises(RuntimeError):
            await ingest_document(session, doc, b"some text here", _BoomEmbedder(),
                                  embedding_model="m")
        assert doc.status == "failed"
        assert "embed boom" in (doc.error or "")
        count = len((await session.execute(
            select(Chunk).where(Chunk.document_id == doc.id))).scalars().all())
        assert count == 0
