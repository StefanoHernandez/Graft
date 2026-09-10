"""One ingestion attempt, end to end.

Split into short transactions with the provider work outside all of them: an
embedding call can take a minute, and a row lock held for a minute is an outage.
Ownership is enforced by the run id from `jobs`, so a duplicated job, a resumed
worker or a stale attempt cannot publish over fresher work.
"""
from __future__ import annotations

import asyncio
import contextlib
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from ..models import Bot, Chunk, Document
from ..providers.base import PROVIDER_INVALID_RESPONSE, EmbeddingProvider, ProviderError
from ..providers.config import EmbeddingConfig
from ..providers.fingerprint import embedding_fingerprint
from .chunking import chunk_sections
from .jobs import (
    DEFAULT_LEASE_SECONDS,
    DEFAULT_MAX_ATTEMPTS,
    claim_document,
    fail_document,
    finish_document,
    heartbeat_document,
)
from .parse_worker import parse_in_subprocess
from .storage import source_path
from .types import ParseError

DEFAULT_BATCH_SIZE = 32
DEFAULT_HEARTBEAT_SECONDS = 30


class ClaimFailed(Exception):
    """Another worker owns this document, or its attempts are exhausted."""


async def ingest_document(
    sessionmaker: async_sessionmaker,
    document_id: uuid.UUID,
    embedder: EmbeddingProvider,
    *,
    embedding_model: str,
    storage_root: Path,
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
    batch_size: int = DEFAULT_BATCH_SIZE,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    heartbeat_seconds: float = DEFAULT_HEARTBEAT_SECONDS,
    parse_timeout: float = 30.0,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> int:
    """Parse, chunk, embed and publish one document. Returns the chunk count.

    Takes a sessionmaker and an id rather than a live ORM object: the attempt
    outlives any single session, and an object attached to a session held open
    across a provider call is exactly the lock we are avoiding.
    """
    async with sessionmaker() as session:
        run_id = await claim_document(
            session,
            document_id,
            datetime.now(UTC),
            lease_seconds=lease_seconds,
            max_attempts=max_attempts,
        )
        if run_id is None:
            raise ClaimFailed(str(document_id))
        filename, mime_type, storage_key, fingerprint = await _attempt_inputs(
            session, document_id
        )

    heartbeat = asyncio.create_task(
        _heartbeat(sessionmaker, document_id, run_id, heartbeat_seconds, lease_seconds)
    )
    try:
        if not storage_key:
            # A document ingested before originals were kept: there is nothing to
            # re-read, and no provider call could help.
            raise ParseError("missing_source")

        sections = await parse_in_subprocess(
            source_path(storage_root, storage_key),
            filename,
            mime_type,
            timeout=parse_timeout,
        )
        drafts = chunk_sections(sections, size=chunk_size, overlap=chunk_overlap)
        vectors = await _embed_in_batches(embedder, drafts, embedding_model, batch_size)

        async with sessionmaker() as session:
            document = await session.get(Document, document_id)
            if document is None:
                raise ClaimFailed(str(document_id))
            chunks = [
                Chunk(
                    document_id=document_id,
                    bot_id=document.bot_id,
                    content=draft.content,
                    embedding=vector,
                    embedding_dim=len(vector),
                    position=index,
                    chunk_metadata=draft.metadata,
                )
                for index, (draft, vector) in enumerate(zip(drafts, vectors, strict=True))
            ]
            published = await finish_document(
                session, document_id, run_id, fingerprint, chunks
            )
        if not published:
            # Someone reclaimed, deleted or reconfigured the document while we
            # were embedding. The work is dropped, not forced through.
            raise ClaimFailed(str(document_id))
        return len(chunks)
    except (ClaimFailed, asyncio.CancelledError):
        # A cancelled attempt (worker shutting down) is not a failed document:
        # leaving it `processing` lets the lease expire and the dispatcher retry.
        raise
    except Exception as exc:
        code = getattr(exc, "code", None) or "internal_error"
        async with sessionmaker() as session:
            await fail_document(session, document_id, run_id, code)
        raise
    finally:
        heartbeat.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat


async def _attempt_inputs(session, document_id: uuid.UUID) -> tuple[str, str, str | None, str]:
    row = (
        await session.execute(
            select(
                Document.filename,
                Document.mime_type,
                Document.storage_key,
                Bot.embedding_config,
            )
            .join(Bot, Bot.id == Document.bot_id)
            .where(Document.id == document_id)
        )
    ).one()
    fingerprint = embedding_fingerprint(EmbeddingConfig(**row.embedding_config))
    return row.filename, row.mime_type, row.storage_key, fingerprint


async def _embed_in_batches(
    embedder: EmbeddingProvider,
    drafts,
    model: str,
    batch_size: int,
) -> list[list[float]]:
    """Embed in bounded batches, refusing a batch that changes dimension.

    Providers cap how much they accept per call, and a mixed-dimension document
    would poison every later `<=>` comparison for that bot.
    """
    vectors: list[list[float]] = []
    dimension: int | None = None
    for start in range(0, len(drafts), batch_size):
        batch = [d.content for d in drafts[start : start + batch_size]]
        produced = await embedder.embed(batch, model=model)
        if len(produced) != len(batch):
            raise ProviderError(PROVIDER_INVALID_RESPONSE)
        for vector in produced:
            if dimension is None:
                dimension = len(vector)
            if len(vector) != dimension:
                raise ProviderError(PROVIDER_INVALID_RESPONSE)
        vectors.extend(produced)
    return vectors


async def _heartbeat(
    sessionmaker: async_sessionmaker,
    document_id: uuid.UUID,
    run_id: uuid.UUID,
    interval: float,
    lease_seconds: int,
) -> None:
    """Keep the lease alive while the attempt runs; stop once it is not ours."""
    while True:
        await asyncio.sleep(interval)
        async with sessionmaker() as session:
            still_ours = await heartbeat_document(
                session, document_id, run_id, datetime.now(UTC), lease_seconds=lease_seconds
            )
        if not still_ours:
            return
