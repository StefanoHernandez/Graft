"""Ownership of one ingestion attempt: claim, heartbeat, publish, fail.

Each function owns a short transaction of its own. Nothing here calls a provider:
parsing and embedding happen between these calls, never inside them, so a slow
model never holds a row lock.

The run id is the fencing token. An at-least-once queue can start the same
document twice, and a worker can freeze long enough for its lease to expire, so
a result is only published when the row still says this run owns it.
"""
from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Chunk, Document
from ..providers.config import EmbeddingConfig
from ..providers.fingerprint import embedding_fingerprint

DEFAULT_LEASE_SECONDS = 120
DEFAULT_MAX_ATTEMPTS = 3

_CLAIM = text("""
    UPDATE documents
    SET status = 'processing',
        ingestion_run_id = :run_id,
        lease_expires_at = :lease_end,
        attempt_count = attempt_count + 1
    WHERE id = :id
      AND attempt_count < :max_attempts
      AND (status = 'pending'
           OR (status = 'processing' AND lease_expires_at < :now))
    RETURNING id
""")


async def claim_document(
    session: AsyncSession,
    document_id: uuid.UUID,
    now: datetime,
    *,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> uuid.UUID | None:
    """Take ownership of a document, or return None if someone else has it.

    One UPDATE decides the winner, so two workers racing on the same document
    cannot both proceed. A document whose attempts are exhausted is never
    claimed again: it must end as `failed`, not loop forever.
    """
    run_id = uuid.uuid4()
    result = await session.execute(
        _CLAIM,
        {
            "run_id": run_id,
            "lease_end": now + timedelta(seconds=lease_seconds),
            "now": now,
            "id": document_id,
            "max_attempts": max_attempts,
        },
    )
    claimed = result.first() is not None
    await session.commit()
    return run_id if claimed else None


async def heartbeat_document(
    session: AsyncSession,
    document_id: uuid.UUID,
    run_id: uuid.UUID,
    now: datetime,
    *,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> bool:
    """Extend this run's lease. False means the run no longer owns the document."""
    result = await session.execute(
        text("""
            UPDATE documents
            SET lease_expires_at = :lease_end
            WHERE id = :id AND ingestion_run_id = :run_id
            RETURNING id
        """),
        {
            "lease_end": now + timedelta(seconds=lease_seconds),
            "id": document_id,
            "run_id": run_id,
        },
    )
    extended = result.first() is not None
    await session.commit()
    return extended


async def _locked_document(session: AsyncSession, document_id: uuid.UUID) -> Document | None:
    return (
        await session.execute(
            select(Document).where(Document.id == document_id).with_for_update()
        )
    ).scalar_one_or_none()


async def finish_document(
    session: AsyncSession,
    document_id: uuid.UUID,
    run_id: uuid.UUID,
    fingerprint: str,
    chunks: Sequence[Chunk],
    *,
    expected_fingerprint: str | None = None,
) -> bool:
    """Publish a finished attempt atomically. False means the work was stale.

    The row is locked first and re-checked: the document may have been deleted,
    reclaimed by another worker, or had its embedding config changed while this
    attempt was out embedding. In all three cases the result is thrown away —
    republishing it would resurrect a deleted document or mix vector spaces.
    """
    document = await _locked_document(session, document_id)
    if document is None or document.ingestion_run_id != run_id:
        await session.rollback()
        return False

    current = expected_fingerprint
    if current is None:
        current = await _bot_fingerprint(session, document.bot_id)
    if current is not None and current != fingerprint:
        await session.rollback()
        return False

    await session.execute(delete(Chunk).where(Chunk.document_id == document_id))
    session.add_all(list(chunks))
    document.status = "ready"
    document.chunk_count = len(chunks)
    document.embedding_fingerprint = fingerprint
    # A document that succeeded must not keep showing the previous failure.
    document.error = None
    document.lease_expires_at = None
    document.ingestion_run_id = None
    document.attempt_count = 0
    await session.commit()
    return True


async def fail_document(
    session: AsyncSession,
    document_id: uuid.UUID,
    run_id: uuid.UUID,
    code: str,
) -> bool:
    """Mark this run's attempt failed. Only the owning run may do so.

    `code` is a stable public code, never a provider message: those can embed the
    API key or the request body.
    """
    result = await session.execute(
        text("""
            UPDATE documents
            SET status = 'failed', error = :code, lease_expires_at = NULL
            WHERE id = :id AND ingestion_run_id = :run_id
            RETURNING id
        """),
        {"code": code, "id": document_id, "run_id": run_id},
    )
    marked = result.first() is not None
    await session.commit()
    return marked


async def _bot_fingerprint(session: AsyncSession, bot_id: uuid.UUID) -> str | None:
    from ..models import Bot

    config = (
        await session.execute(select(Bot.embedding_config).where(Bot.id == bot_id))
    ).scalar_one_or_none()
    if not config:
        return None
    return embedding_fingerprint(EmbeddingConfig(**config))
