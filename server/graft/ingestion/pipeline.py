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
    """Parse, chunk, embed, and store a document's chunks.

    The caller must pass an already-persisted Document (a committed row) and
    cedes session ownership to this function, which commits on success and,
    on failure, rolls back, marks the document ``failed`` with the error, and
    re-raises. The embedder is dependency-injected (built by the caller from
    the bot's embedding_config).
    """
    try:
        document.status = "processing"
        await session.flush()

        text = parse_document(document.filename, document.mime_type, data)
        pieces = chunk_text(text, size=chunk_size, overlap=chunk_overlap)

        if not pieces:
            await replace_document_chunks(session, document.id, [])
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
