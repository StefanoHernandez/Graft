# Graft — Phase 3a: Ingestion Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the synchronous document-ingestion pipeline — a `chunks` table + store, document parsing (PDF/Markdown/plain text) and text chunking, and an `ingest_document()` function that parses → chunks → embeds (via an injected `EmbeddingProvider`) → stores chunks and updates the document's status.

**Architecture:** Ingestion lives in a new `graft.ingestion` package with focused, independently testable units: `parsing` (bytes → text), `chunking` (text → overlapping pieces), `store` (persist chunks for a document), `pipeline` (orchestration). Chunks are stored in a single `chunks` table with a **dimensionless** pgvector column (`vector`, no fixed dimension) per spec §6.1 — exact-KNN retrieval comes in Phase 4; no ANN index here. The pipeline takes the embedder by dependency injection so it is unit-testable without network; the caller (Phase 6 upload endpoint / Phase 3b worker) builds the embedder from the bot's `embedding_config` via `graft.providers.factory`.

**Tech Stack:** Python 3.12, SQLAlchemy 2 async, pgvector (`Vector()` dimensionless), Alembic, `pypdf` (PDF text extraction). Reuses `graft.models`, `graft.providers`. Tests: pytest + testcontainers Postgres + a fake embedder.

**Spec:** `docs/superpowers/specs/2026-09-08-graft-design.md` (§4.4 Ingestion, §5 chunks, §6.1 vector storage)

## Global Constraints

- **Python** `>=3.12`; dep manager `uv`; commands `uv run <cmd>` from `server/`.
- **`chunks` table** uses a **dimensionless** pgvector column: `embedding vector` (SQLAlchemy `pgvector.sqlalchemy.Vector()` with no dimension). Store the model's dimension separately in `embedding_dim`. NO ANN index in this phase (exact KNN is Phase 4).
- The chunk's metadata column is **named `metadata`** in SQL but mapped to the Python attribute **`chunk_metadata`** (SQLAlchemy Declarative reserves the `metadata` attribute name).
- **Parsing** supports PDF (`pypdf`), Markdown, and plain text in this phase. `unstructured` is a deferred optional backend (not in this plan). Unsupported types raise `ValueError`.
- **Chunking** is character-based with `size`/`overlap` (defaults 1000/200); deterministic; strips whitespace; returns `[]` for empty input; rejects `size <= 0` or `overlap` not in `[0, size)`.
- **`ingest_document`** takes the embedder + embedding model by dependency injection (no factory call inside); on any failure it marks the document `failed` with the error and re-raises.
- Document status lifecycle: `pending → processing → ready | failed`.
- Every new Python file passes `uv run ruff check .` clean; test output pristine (0 warnings). Run `uv run ruff check --fix .` before committing.
- Tests live flat under `server/tests/`.

---

### Task 1: `chunks` table — model + migration

**Files:**
- Create: `server/graft/models/chunk.py`
- Modify: `server/graft/models/__init__.py` (export `Chunk`)
- Create: `server/migrations/versions/0002_chunks.py`
- Test: `server/tests/test_chunks_model.py`

**Interfaces:**
- Consumes: `graft.models.base.{Base,UUIDMixin,TimestampMixin}`; existing `documents`/`bots` tables (FK targets).
- Produces: `graft.models.Chunk` with columns `id`, `document_id` (FK documents.id, indexed), `bot_id` (FK bots.id, indexed), `content: str`, `embedding_dim: int`, `embedding: list[float]` (dimensionless `Vector()`), `chunk_metadata: dict` (SQL column `metadata`), `position: int`, timestamps. Alembic `head` now creates the `chunks` table.

- [ ] **Step 1: Implement `server/graft/models/chunk.py`**

```python
import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, UUIDMixin


class Chunk(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "chunks"

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    bot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bots.id", ondelete="CASCADE"), index=True
    )
    content: Mapped[str] = mapped_column(Text)
    embedding_dim: Mapped[int] = mapped_column(Integer)
    embedding: Mapped[list[float]] = mapped_column(Vector())
    # SQL column is "metadata"; the Python attribute is chunk_metadata because
    # SQLAlchemy Declarative reserves the `metadata` attribute name.
    chunk_metadata: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    position: Mapped[int] = mapped_column(Integer)
```

- [ ] **Step 2: Export `Chunk` from `server/graft/models/__init__.py`**

Add `from .chunk import Chunk` and include `"Chunk"` in `__all__` (place it after `Bot`/`BotMember` imports; keep the file's existing structure).

- [ ] **Step 3: Write the failing test** — `server/tests/test_chunks_model.py`

```python
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from graft.models import Bot, Chunk, Document


async def test_chunk_roundtrip(db_engine):
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        bot = Bot(name="b", widget_key=f"wk_{uuid.uuid4().hex}")
        session.add(bot)
        await session.flush()
        doc = Document(bot_id=bot.id, filename="f.txt", mime_type="text/plain")
        session.add(doc)
        await session.flush()
        session.add(Chunk(
            document_id=doc.id, bot_id=bot.id, content="hello",
            embedding=[0.1, 0.2, 0.3], embedding_dim=3, position=0,
            chunk_metadata={"k": "v"},
        ))
        await session.commit()

        got = (await session.execute(
            select(Chunk).where(Chunk.document_id == doc.id))).scalar_one()
        assert got.content == "hello"
        assert got.embedding_dim == 3
        assert len(got.embedding) == 3
        assert got.chunk_metadata == {"k": "v"}
        assert got.position == 0
```

- [ ] **Step 4: Run test to verify it fails**

Run: `cd server && uv run pytest tests/test_chunks_model.py -v`
Expected: FAIL — `chunks` table does not exist (no migration yet) / `ImportError: cannot import name 'Chunk'`.

- [ ] **Step 5: Write the migration** — `server/migrations/versions/0002_chunks.py`

```python
"""chunks table

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chunks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("document_id", UUID(as_uuid=True),
                  sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("bot_id", UUID(as_uuid=True),
                  sa.ForeignKey("bots.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("embedding_dim", sa.Integer, nullable=False),
        sa.Column("embedding", Vector(), nullable=False),
        sa.Column("metadata", JSONB, nullable=False, server_default="{}"),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("chunks")
```

- [ ] **Step 6: Lint, then run the test to verify it passes**

Run: `cd server && uv run ruff check --fix . && uv run ruff check . && uv run pytest tests/test_chunks_model.py -v`
Expected: ruff clean; the test PASSES (the `migrated` fixture applies `0002` to the container, then the round-trip works).

- [ ] **Step 7: Commit**

```bash
git add server/graft/models/chunk.py server/graft/models/__init__.py server/migrations/versions/0002_chunks.py server/tests/test_chunks_model.py
git commit -m "feat(server): chunks table (dimensionless pgvector) + model"
```
End the commit message body with:
Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

---

### Task 2: Document parsing + text chunking

**Files:**
- Create: `server/graft/ingestion/__init__.py`
- Create: `server/graft/ingestion/parsing.py`
- Create: `server/graft/ingestion/chunking.py`
- Modify: `server/pyproject.toml` (add `pypdf`)
- Test: `server/tests/test_ingestion_parsing.py`
- Test: `server/tests/test_ingestion_chunking.py`

**Interfaces:**
- Consumes: `pypdf.PdfReader`.
- Produces:
  - `graft.ingestion.parsing.parse_document(filename: str, mime_type: str, data: bytes) -> str`
  - `graft.ingestion.chunking.chunk_text(text: str, *, size: int = 1000, overlap: int = 200) -> list[str]`

- [ ] **Step 1: Add `pypdf` to `server/pyproject.toml`**

In `[project]` `dependencies`, add:

```toml
    "pypdf>=4.0",
```

- [ ] **Step 2: Write the failing tests**

`server/tests/test_ingestion_chunking.py`:

```python
import pytest

from graft.ingestion.chunking import chunk_text


def test_empty_returns_no_chunks():
    assert chunk_text("   \n  ") == []


def test_short_text_single_chunk():
    assert chunk_text("hello world", size=1000, overlap=200) == ["hello world"]


def test_splits_with_overlap():
    text = "abcdefghij" * 300  # 3000 chars
    chunks = chunk_text(text, size=1000, overlap=200)
    # step = 800 -> starts at 0, 800, 1600, 2400 -> 4 chunks
    assert len(chunks) == 4
    assert all(len(c) <= 1000 for c in chunks)
    # overlap: end of chunk 0 reappears at start of chunk 1
    assert chunks[0][-200:] == chunks[1][:200]


def test_invalid_params_raise():
    with pytest.raises(ValueError):
        chunk_text("x", size=0)
    with pytest.raises(ValueError):
        chunk_text("x", size=100, overlap=100)
```

`server/tests/test_ingestion_parsing.py`:

```python
import pytest

from graft.ingestion import parsing


def test_parse_plain_text():
    assert parsing.parse_document("a.txt", "text/plain", b"hello") == "hello"


def test_parse_markdown_by_extension():
    assert parsing.parse_document("a.md", "", b"# Title\n\nbody") == "# Title\n\nbody"


def test_parse_pdf_joins_page_text(monkeypatch):
    class _Page:
        def __init__(self, text):
            self._text = text

        def extract_text(self):
            return self._text

    class _Reader:
        def __init__(self, *args, **kwargs):
            self.pages = [_Page("Page one"), _Page("Page two")]

    monkeypatch.setattr(parsing, "PdfReader", _Reader)
    assert parsing.parse_document("x.pdf", "application/pdf", b"%PDF-fake") == "Page one\nPage two"


def test_parse_unsupported_raises():
    with pytest.raises(ValueError):
        parsing.parse_document("a.bin", "application/octet-stream", b"\x00\x01")
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd server && uv run pytest tests/test_ingestion_parsing.py tests/test_ingestion_chunking.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'graft.ingestion'`.

- [ ] **Step 4: Implement `server/graft/ingestion/chunking.py`**

```python
from __future__ import annotations


def chunk_text(text: str, *, size: int = 1000, overlap: int = 200) -> list[str]:
    if size <= 0:
        raise ValueError("size must be positive")
    if not 0 <= overlap < size:
        raise ValueError("overlap must be in [0, size)")
    text = text.strip()
    if not text:
        return []
    step = size - overlap
    chunks: list[str] = []
    for start in range(0, len(text), step):
        piece = text[start : start + size].strip()
        if piece:
            chunks.append(piece)
    return chunks
```

- [ ] **Step 5: Implement `server/graft/ingestion/parsing.py`** (and empty `server/graft/ingestion/__init__.py`)

```python
from __future__ import annotations

from io import BytesIO

from pypdf import PdfReader

_TEXT_MIME = {"text/plain", "text/markdown"}
_TEXT_EXT = (".txt", ".md", ".markdown")


def parse_document(filename: str, mime_type: str, data: bytes) -> str:
    name = filename.lower()
    if mime_type == "application/pdf" or name.endswith(".pdf"):
        reader = PdfReader(BytesIO(data))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    if mime_type in _TEXT_MIME or name.endswith(_TEXT_EXT):
        return data.decode("utf-8", errors="replace")
    raise ValueError(f"Unsupported document type: {mime_type or filename!r}")
```

- [ ] **Step 6: Lint, then run the tests to verify they pass**

Run: `cd server && uv run ruff check --fix . && uv run ruff check . && uv run pytest tests/test_ingestion_parsing.py tests/test_ingestion_chunking.py -v`
Expected: ruff clean; all parsing + chunking tests PASS.

- [ ] **Step 7: Commit**

```bash
git add server/graft/ingestion/__init__.py server/graft/ingestion/parsing.py server/graft/ingestion/chunking.py server/pyproject.toml server/uv.lock server/tests/test_ingestion_parsing.py server/tests/test_ingestion_chunking.py
git commit -m "feat(server): document parsing (pdf/md/txt) and text chunking"
```
End the commit message body with:
Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

---

### Task 3: Ingestion pipeline + chunk store

**Files:**
- Create: `server/graft/ingestion/store.py`
- Create: `server/graft/ingestion/pipeline.py`
- Test: `server/tests/test_ingestion_pipeline.py`

**Interfaces:**
- Consumes: `graft.models.{Chunk,Document}`, `graft.providers.base.EmbeddingProvider`, `graft.ingestion.{parsing.parse_document, chunking.chunk_text}`.
- Produces:
  - `graft.ingestion.store.replace_document_chunks(session, document_id, chunks) -> None` (deletes existing chunks for the document, adds the new ones).
  - `graft.ingestion.pipeline.ingest_document(session, document, data, embedder, *, embedding_model, chunk_size=1000, chunk_overlap=200) -> int` — returns the number of chunks stored; sets `document.status`/`chunk_count`; on failure sets `status="failed"`, `error`, and re-raises.

- [ ] **Step 1: Write the failing test** — `server/tests/test_ingestion_pipeline.py`

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd server && uv run pytest tests/test_ingestion_pipeline.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'graft.ingestion.pipeline'`.

- [ ] **Step 3: Implement `server/graft/ingestion/store.py`**

```python
from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Chunk


async def replace_document_chunks(
    session: AsyncSession, document_id, chunks: Sequence[Chunk]
) -> None:
    await session.execute(delete(Chunk).where(Chunk.document_id == document_id))
    session.add_all(list(chunks))
```

- [ ] **Step 4: Implement `server/graft/ingestion/pipeline.py`**

```python
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Chunk, Document
from ..providers.base import EmbeddingProvider
from .chunking import chunk_text
from .parsing import parse_document
from .store import replace_document_chunks


async def ingest_document(
    session: AsyncSession,
    document: Document,
    data: bytes,
    embedder: EmbeddingProvider,
    *,
    embedding_model: str,
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
) -> int:
    try:
        document.status = "processing"
        await session.flush()

        text = parse_document(document.filename, document.mime_type, data)
        pieces = chunk_text(text, size=chunk_size, overlap=chunk_overlap)

        if not pieces:
            document.status = "ready"
            document.chunk_count = 0
            await session.commit()
            return 0

        vectors = await embedder.embed(pieces, model=embedding_model)
        chunks = [
            Chunk(
                document_id=document.id,
                bot_id=document.bot_id,
                content=piece,
                embedding=vector,
                embedding_dim=len(vector),
                position=index,
                chunk_metadata={},
            )
            for index, (piece, vector) in enumerate(zip(pieces, vectors, strict=True))
        ]
        await replace_document_chunks(session, document.id, chunks)
        document.status = "ready"
        document.chunk_count = len(chunks)
        await session.commit()
        return len(chunks)
    except Exception as exc:
        await session.rollback()
        document.status = "failed"
        document.error = str(exc)
        await session.commit()
        raise
```

- [ ] **Step 5: Lint, then run the full suite to verify it passes**

Run: `cd server && uv run ruff check --fix . && uv run ruff check . && uv run pytest -v`
Expected: ruff clean; ALL tests pass (every prior test + the three ingestion pipeline tests), pristine.

- [ ] **Step 6: Commit**

```bash
git add server/graft/ingestion/store.py server/graft/ingestion/pipeline.py server/tests/test_ingestion_pipeline.py
git commit -m "feat(server): synchronous ingestion pipeline (parse, chunk, embed, store)"
```
End the commit message body with:
Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

---

## Phase 3a Definition of Done

- `cd server && uv run pytest -v` → all green (prior suite + chunks model, parsing, chunking, pipeline), pristine.
- `uv run ruff check .` → clean.
- `chunks` table exists via Alembic `head` (dimensionless `vector` column, indexes on `document_id`/`bot_id`).
- `parse_document` handles PDF/Markdown/plain text and rejects unsupported types; `chunk_text` splits deterministically with overlap.
- `ingest_document` parses → chunks → embeds (injected embedder) → stores chunks, sets `ready`/`chunk_count`, and on failure sets `failed`/`error` and re-raises.

## What Phase 3a deliberately excludes (later)

- **Phase 3b:** Redis queue + async background worker that builds the embedder from the bot's `embedding_config` (via `graft.providers.factory`) and calls `ingest_document`; document enqueue on upload.
- `unstructured` parser backend (optional heavy extra).
- The HTTP upload endpoint — Phase 6 (Admin API).
- Retrieval / similarity search over chunks — Phase 4 (RAG + Chat API).
