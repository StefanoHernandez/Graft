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
