"""Exact nearest-neighbour search over one bot's current vector space.

Every filter here exists to stop a comparison that would be meaningless:
another bot's corpus, a document that is not `ready`, or chunks embedded by a
different model. Two vectors of the same length from different models are not
comparable, so the filter is the **fingerprint**, never the dimension alone.
"""
from __future__ import annotations

import math
import uuid
from dataclasses import dataclass

from pgvector.sqlalchemy import Vector
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

DEFAULT_TOP_K = 5
DEFAULT_MIN_SCORE = 0.5


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    content: str
    score: float
    filename: str
    page: int | None
    heading: str | None


# The CTE is MATERIALIZED so the planner cannot push the distance operator down
# and evaluate `<=>` on rows of another dimension, which errors at runtime.
_SEARCH = text("""
    WITH eligible AS MATERIALIZED (
        SELECT c.id, c.document_id, c.content, c.metadata, c.embedding, d.filename
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE c.bot_id = :bot_id
          AND d.bot_id = :bot_id
          AND d.status = 'ready'
          AND d.embedding_fingerprint = :fingerprint
          AND c.embedding_dim = :dim
          AND vector_dims(c.embedding) = :dim
    )
    SELECT id, document_id, content, metadata, filename,
           1 - (embedding <=> :query_vector) AS score
    FROM eligible
    WHERE 1 - (embedding <=> :query_vector) >= :min_score
    ORDER BY embedding <=> :query_vector, id
    LIMIT :top_k
""").bindparams(bindparam("query_vector", type_=Vector()))


async def retrieve(
    session: AsyncSession,
    bot_id: uuid.UUID,
    fingerprint: str,
    query_vector: list[float],
    *,
    top_k: int = DEFAULT_TOP_K,
    min_score: float = DEFAULT_MIN_SCORE,
) -> list[RetrievedChunk]:
    """Return the closest eligible chunks, best score first.

    `score` is cosine similarity in [-1, 1]; `min_score` is the abstention line,
    and it has to be calibrated against a real corpus rather than trusted.
    """
    _validate(query_vector)
    rows = await session.execute(
        _SEARCH,
        {
            "bot_id": bot_id,
            "fingerprint": fingerprint,
            "dim": len(query_vector),
            "query_vector": query_vector,
            "min_score": min_score,
            "top_k": top_k,
        },
    )
    return [
        RetrievedChunk(
            chunk_id=row.id,
            document_id=row.document_id,
            content=row.content,
            score=float(row.score),
            filename=row.filename,
            page=(row.metadata or {}).get("page"),
            heading=(row.metadata or {}).get("heading"),
        )
        for row in rows
    ]


def _validate(query_vector: list[float]) -> None:
    """A zero or non-finite query has no direction; cosine distance is undefined."""
    if not query_vector:
        raise ValueError("query vector is empty")
    if not all(math.isfinite(value) for value in query_vector):
        raise ValueError("query vector has non-finite values")
    if not any(query_vector):
        raise ValueError("query vector is all zeros")
