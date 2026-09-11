"""The arq worker: one job per document, plus a sweep that rebuilds lost work.

Retry policy lives here, not in the pipeline. A permanent failure (bad key, bad
model, unparseable file) fails the document immediately; a transient one puts it
back in `pending` and defers, with the attempt still counted so three tries is
three tries. The SDK's own retries are switched off, because stacking them under
this multiplies both the wall clock and the bill with nobody deciding to.
"""
from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

from arq import Retry, cron
from arq.connections import RedisSettings
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_engine, get_sessionmaker
from ..models import Bot, Document
from ..providers.base import ProviderError
from ..providers.config import EmbeddingConfig
from ..providers.factory import build_embedder
from .jobs import DEFAULT_MAX_ATTEMPTS
from .pipeline import ClaimFailed, ingest_document
from .queue import JOB_NAME, enqueue_document

logger = logging.getLogger(__name__)

# Waits before the second and third attempt. Past the last entry the attempt
# ceiling has been reached anyway.
RETRY_DELAYS = (10, 30)
JOB_TIMEOUT_SECONDS = 600
DISPATCH_LIMIT = 200


def _storage_root() -> Path:
    return get_settings().storage_root


def _sessionmaker(ctx: dict):
    """Resources come from the arq context, built once in `on_startup`."""
    return ctx.get("sessionmaker") or get_sessionmaker()


async def ingest_job(ctx: dict, document_id: str) -> int | None:
    """Ingest one document. Returns the chunk count, or None if there was nothing to do."""
    sessionmaker = _sessionmaker(ctx)
    doc_id = uuid.UUID(document_id)

    async with sessionmaker() as session:
        row = (
            await session.execute(
                select(Document.status, Bot.embedding_config)
                .join(Bot, Bot.id == Document.bot_id)
                .where(Document.id == doc_id)
            )
        ).one_or_none()
    if row is None:
        # Deleted between the enqueue and now: nothing to resurrect.
        logger.info("ingest_job: document %s no longer exists", document_id)
        return None
    if row.status == "ready":
        # A crash between the commit and the ack replays the job. The work is done.
        return None

    embedder = build_embedder(EmbeddingConfig(**row.embedding_config), max_retries=0)
    try:
        return await ingest_document(
            sessionmaker,
            doc_id,
            embedder,
            embedding_model=row.embedding_config["model"],
            storage_root=_storage_root(),
        )
    except ClaimFailed:
        # Another worker owns it, or the attempts are spent. The dispatcher
        # decides what happens to an exhausted document.
        return None
    except ProviderError as exc:
        if not exc.retryable:
            raise
        async with sessionmaker() as session:
            await requeue_document(session, doc_id)
        raise Retry(defer=RETRY_DELAYS[min(ctx.get("job_try", 1), len(RETRY_DELAYS)) - 1])
    finally:
        if hasattr(embedder, "aclose"):
            await embedder.aclose()


async def requeue_document(session: AsyncSession, document_id: uuid.UUID) -> None:
    """Make a transiently failed document claimable again, keeping its attempt count."""
    await session.execute(
        text("""
            UPDATE documents
            SET status = 'pending', error = NULL,
                ingestion_run_id = NULL, lease_expires_at = NULL
            WHERE id = :id AND status = 'failed'
        """),
        {"id": document_id},
    )
    await session.commit()


async def dispatch_pending(ctx: dict) -> list[str]:
    """Rebuild the queue from the database, and end documents that can never run.

    Redis can lose its queue, or never receive an enqueue at all because it was
    down when the upload committed. The sweep is what makes those cases cost
    latency instead of a lost document.
    """
    sessionmaker = _sessionmaker(ctx)
    now = datetime.now(UTC)
    async with sessionmaker() as session:
        claimable = (
            await session.execute(
                text("""
                    SELECT id FROM documents
                    WHERE attempt_count < :max_attempts
                      AND (status = 'pending'
                           OR (status = 'processing' AND lease_expires_at < :now))
                    ORDER BY updated_at
                    LIMIT :limit
                """),
                {"max_attempts": DEFAULT_MAX_ATTEMPTS, "now": now, "limit": DISPATCH_LIMIT},
            )
        ).scalars().all()

        # Never leave a document stuck in processing: out of attempts is an outcome.
        await session.execute(
            text("""
                UPDATE documents
                SET status = 'failed', error = 'attempts_exhausted', lease_expires_at = NULL
                WHERE attempt_count >= :max_attempts
                  AND status IN ('pending', 'processing')
                  AND (lease_expires_at IS NULL OR lease_expires_at < :now)
            """),
            {"max_attempts": DEFAULT_MAX_ATTEMPTS, "now": now},
        )
        await session.commit()

    redis = ctx["redis"]
    for document_id in claimable:
        await enqueue_document(redis, document_id)
    return [str(document_id) for document_id in claimable]


class WorkerSettings:
    """`uv run arq graft.ingestion.worker.WorkerSettings`."""

    functions: ClassVar = [ingest_job]
    cron_jobs: ClassVar = [cron(dispatch_pending, second=0, run_at_startup=True)]
    # One document at a time: parsing and embedding are the expensive part, and a
    # second concurrent job would double provider pressure for no throughput win
    # until that is measured.
    max_jobs = 1
    job_timeout = JOB_TIMEOUT_SECONDS
    keep_result = 0
    max_tries = DEFAULT_MAX_ATTEMPTS

    @staticmethod
    def redis_settings() -> RedisSettings:
        return RedisSettings.from_dsn(get_settings().redis_url)

    @staticmethod
    async def on_startup(ctx: dict) -> None:
        ctx["sessionmaker"] = get_sessionmaker()

    @staticmethod
    async def on_shutdown(ctx: dict) -> None:
        await get_engine().dispose()


__all__ = ["JOB_NAME", "WorkerSettings", "dispatch_pending", "ingest_job"]
