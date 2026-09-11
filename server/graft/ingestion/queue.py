"""Enqueueing ingestion work.

Jobs carry a document id and nothing else: file bytes would bloat Redis and
provider keys have no business leaving the database. The worker re-reads
everything it needs, so a job that arrives late still sees current state.
"""
from __future__ import annotations

import uuid

from arq.connections import ArqRedis
from arq.jobs import Job

JOB_NAME = "ingest_job"


def job_id(document_id: uuid.UUID | str) -> str:
    """One stable id per document, so a duplicate enqueue is a no-op."""
    return f"ingest:{document_id}"


async def enqueue_document(redis: ArqRedis, document_id: uuid.UUID | str) -> Job | None:
    """Hint the worker. Returns None when the job is already queued.

    The return value is not an error path: the dispatcher re-enqueues on every
    sweep, and losing the hint only costs latency — the database still holds the
    work list.
    """
    return await redis.enqueue_job(
        JOB_NAME, str(document_id), _job_id=job_id(document_id)
    )
