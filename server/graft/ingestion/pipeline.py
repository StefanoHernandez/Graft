from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Chunk, Document
from ..providers.base import EmbeddingProvider
from .chunking import chunk_sections
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

    A document that yields no text is a failure (``no_extractable_text``), not a
    ready document with zero chunks: an admin has to know the upload was useless.

    The caller must pass an already-persisted Document (a committed row) and
    cedes session ownership to this function, which commits on success and,
    on failure, rolls back, marks the document ``failed`` with the error, and
    re-raises. The embedder is dependency-injected (built by the caller from
    the bot's embedding_config).
    """
    try:
        document.status = "processing"
        await session.flush()

        sections = parse_document(document.filename, document.mime_type, data)
        drafts = chunk_sections(sections, size=chunk_size, overlap=chunk_overlap)

        vectors = await embedder.embed([d.content for d in drafts], model=embedding_model)
        chunks = [
            Chunk(
                document_id=document.id,
                bot_id=document.bot_id,
                content=draft.content,
                embedding=vector,
                embedding_dim=len(vector),
                position=index,
                chunk_metadata=draft.metadata,
            )
            for index, (draft, vector) in enumerate(zip(drafts, vectors, strict=True))
        ]
        await replace_document_chunks(session, document.id, chunks)
        document.status = "ready"
        document.chunk_count = len(chunks)
        # A document that succeeds must not keep displaying the error that failed
        # the previous attempt.
        document.error = None
        await session.commit()
        return len(chunks)
    except Exception as exc:
        await session.rollback()
        document.status = "failed"
        document.error = str(exc)
        await session.commit()
        raise
