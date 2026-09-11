"""Admin API. Every route requires an active owner.

Ordering rules that matter here:
- an API key is encrypted before it is persisted, and never serialized back;
- an upload takes the bot row lock, so it cannot slip past a concurrent change
  of the embedding config and end up in the wrong vector space;
- a delete revokes the database row first and removes the file afterwards — a
  file left behind is an operational chore, a row left behind is a live document.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_session
from ..ingestion.storage import delete_bot_sources, delete_source, save_source
from ..models import Bot, Chunk, Document
from ..providers.base import ProviderError
from ..providers.config import EmbeddingConfig, LLMConfig
from ..providers.factory import build_embedder, build_llm
from ..providers.fingerprint import embedding_fingerprint
from ..security.auth import current_owner
from ..security.crypto import encrypt
from .schemas import (
    BotCreate,
    BotOut,
    BotUpdate,
    DocumentOut,
    Page,
    ProviderCheck,
    ProviderConfigIn,
    ProviderConfigOut,
    ProviderTestOut,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/admin", tags=["admin"], dependencies=[Depends(current_owner)])

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
_READ_BLOCK = 64 * 1024
_ALLOWED = {
    "application/pdf": ".pdf",
    "text/plain": ".txt",
    "text/markdown": ".md",
}
_ALLOWED_EXTENSIONS = (".pdf", ".txt", ".md", ".markdown")


def _store_config(config: ProviderConfigIn | None, previous: dict | None = None) -> dict | None:
    """Turn an input config into what belongs in the database.

    An omitted `api_key` keeps the stored one; an explicit null clears it. That
    distinction is why this reads `model_fields_set` instead of the value.
    """
    if config is None:
        return None
    stored = {
        "provider": config.provider,
        "model": config.model,
        "base_url": config.base_url,
        "api_key": None,
        "api_key_encrypted": True,
    }
    if "api_key" in config.model_fields_set:
        stored["api_key"] = encrypt(config.api_key) if config.api_key else None
    elif previous:
        stored["api_key"] = previous.get("api_key")
    return stored


def _bot_out(bot: Bot) -> BotOut:
    return BotOut(
        id=bot.id,
        name=bot.name,
        widget_key=bot.widget_key,
        allowed_origins=list(bot.allowed_origins or []),
        llm_config=ProviderConfigOut.from_stored(bot.llm_config),
        embedding_config=ProviderConfigOut.from_stored(bot.embedding_config),
        system_prompt=bot.system_prompt or "",
        theme=bot.theme or {},
        retrieval_config=bot.retrieval_config or {},
        created_at=bot.created_at,
    )


async def _get_bot(session: AsyncSession, bot_id: uuid.UUID, *, lock: bool = False) -> Bot:
    query = select(Bot).where(Bot.id == bot_id)
    if lock:
        query = query.with_for_update()
    bot = (await session.execute(query)).scalar_one_or_none()
    if bot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "bot_not_found"})
    return bot


async def _get_document(session: AsyncSession, document_id: uuid.UUID) -> Document:
    document = await session.get(Document, document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "document_not_found"})
    return document


@router.get("/bots", response_model=Page[BotOut])
async def list_bots(
    session: AsyncSession = Depends(get_session),  # noqa: B008
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
) -> Page[BotOut]:
    total = await session.scalar(select(func.count()).select_from(Bot))
    rows = (
        await session.execute(
            select(Bot).order_by(Bot.created_at.desc(), Bot.id).offset(offset).limit(limit)
        )
    ).scalars().all()
    return Page(items=[_bot_out(bot) for bot in rows], total=total or 0)


@router.post("/bots", response_model=BotOut, status_code=status.HTTP_201_CREATED)
async def create_bot(
    body: BotCreate,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> BotOut:
    bot = Bot(
        name=body.name,
        # Public by design: it identifies the bot in a page anyone can read.
        widget_key=secrets.token_urlsafe(32),
        allowed_origins=body.allowed_origins,
        llm_config=_store_config(body.llm_config) or {},
        embedding_config=_store_config(body.embedding_config) or {},
        system_prompt=body.system_prompt,
        theme=body.theme,
        retrieval_config=body.retrieval_config,
    )
    session.add(bot)
    await session.commit()
    return _bot_out(bot)


@router.patch("/bots/{bot_id}", response_model=BotOut)
async def update_bot(
    bot_id: uuid.UUID,
    body: BotUpdate,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> BotOut:
    bot = await _get_bot(session, bot_id, lock=True)

    if body.embedding_config is not None:
        proposed = _store_config(body.embedding_config, bot.embedding_config)
        if await _would_orphan_documents(session, bot, proposed):
            raise HTTPException(
                status.HTTP_409_CONFLICT, detail={"code": "embedding_config_locked"}
            )
        bot.embedding_config = proposed
    if body.llm_config is not None:
        bot.llm_config = _store_config(body.llm_config, bot.llm_config)
    for field in ("name", "allowed_origins", "system_prompt", "theme", "retrieval_config"):
        value = getattr(body, field)
        if value is not None:
            setattr(bot, field, value)
    await session.commit()
    return _bot_out(bot)


async def _would_orphan_documents(session: AsyncSession, bot: Bot, proposed: dict) -> bool:
    """True when the change moves the bot to a different vector space with documents in it.

    Rotating only the API key is not such a change, which is why the comparison
    is on the fingerprint and not on the raw config.
    """
    if not bot.embedding_config:
        return False
    if embedding_fingerprint(EmbeddingConfig(**bot.embedding_config)) == embedding_fingerprint(
        EmbeddingConfig(**proposed)
    ):
        return False
    documents = await session.scalar(
        select(func.count()).select_from(Document).where(Document.bot_id == bot.id)
    )
    return bool(documents)


@router.delete("/bots/{bot_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_bot(
    bot_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> None:
    bot = await _get_bot(session, bot_id)
    await session.delete(bot)
    await session.commit()
    _remove_files(lambda: delete_bot_sources(get_settings().storage_root, bot_id), bot_id)


@router.post("/bots/{bot_id}/provider/test", response_model=ProviderTestOut)
async def test_provider(
    bot_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> ProviderTestOut:
    """Prove the configured models answer, not merely that the key lists models.

    A key can list models it is not allowed to call, so this sends the smallest
    real chat and the smallest real embedding.
    """
    bot = await _get_bot(session, bot_id)
    return ProviderTestOut(
        llm=await _check_llm(bot.llm_config), embedding=await _check_embedding(bot.embedding_config)
    )


async def _check_llm(config: dict | None) -> ProviderCheck:
    if not config:
        return ProviderCheck(ok=False, code="provider_config")
    client = None
    try:
        client = build_llm(LLMConfig(**config))
        async for _ in client.stream_chat(
            [{"role": "user", "content": "ping"}], model=config["model"], max_tokens=1
        ):
            break
        return ProviderCheck(ok=True, code=None)
    except ProviderError as exc:
        return ProviderCheck(ok=False, code=exc.code)
    finally:
        await _aclose(client)


async def _check_embedding(config: dict | None) -> ProviderCheck:
    if not config:
        return ProviderCheck(ok=False, code="provider_config")
    client = None
    try:
        client = build_embedder(EmbeddingConfig(**config))
        await client.embed(["ping"], model=config["model"])
        return ProviderCheck(ok=True, code=None)
    except ProviderError as exc:
        return ProviderCheck(ok=False, code=exc.code)
    finally:
        await _aclose(client)


async def _aclose(client) -> None:
    if client is not None and hasattr(client, "aclose"):
        await client.aclose()


@router.get("/bots/{bot_id}/documents", response_model=Page[DocumentOut])
async def list_documents(
    bot_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
) -> Page[DocumentOut]:
    await _get_bot(session, bot_id)
    total = await session.scalar(
        select(func.count()).select_from(Document).where(Document.bot_id == bot_id)
    )
    rows = (
        await session.execute(
            select(Document)
            .where(Document.bot_id == bot_id)
            .order_by(Document.created_at.desc(), Document.id)
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()
    return Page(items=[DocumentOut.model_validate(r, from_attributes=True) for r in rows],
                total=total or 0)


@router.post(
    "/bots/{bot_id}/documents",
    response_model=DocumentOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_document(
    bot_id: uuid.UUID,
    file: UploadFile = File(...),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> DocumentOut:
    # The row lock is taken before the file is read so an embedding-config change
    # cannot land between the check and the insert.
    await _get_bot(session, bot_id, lock=True)
    mime = _accepted_mime(file)
    data = await _read_within_limit(file)

    document = Document(
        id=uuid.uuid4(),
        bot_id=bot_id,
        filename=file.filename or "upload",
        mime_type=mime,
        status="pending",
        source_sha256=hashlib.sha256(data).hexdigest(),
    )
    storage_root = get_settings().storage_root
    document.storage_key = save_source(storage_root, bot_id, document.id, data)
    try:
        session.add(document)
        await session.commit()
    except Exception:
        # No row means nothing will ever read this file: remove it now rather
        # than leave an orphan nobody can attribute.
        delete_source(storage_root, document.storage_key)
        raise
    return DocumentOut.model_validate(document, from_attributes=True)


def _accepted_mime(file: UploadFile) -> str:
    name = (file.filename or "").lower()
    if file.content_type in _ALLOWED:
        return file.content_type
    if name.endswith(_ALLOWED_EXTENSIONS):
        return "application/pdf" if name.endswith(".pdf") else "text/plain"
    raise HTTPException(
        status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail={"code": "unsupported_type"}
    )


async def _read_within_limit(file: UploadFile) -> bytes:
    """Read in blocks and stop at the ceiling, instead of buffering whatever arrives."""
    data = bytearray()
    while block := await file.read(_READ_BLOCK):
        data.extend(block)
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status.HTTP_413_CONTENT_TOO_LARGE, detail={"code": "file_too_large"}
            )
    return bytes(data)


@router.post("/documents/{document_id}/retry", status_code=status.HTTP_202_ACCEPTED)
async def retry_document(
    document_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> DocumentOut:
    document = await _get_document(session, document_id)
    if document.status != "failed":
        raise HTTPException(status.HTTP_409_CONFLICT, detail={"code": "not_failed"})
    document.status = "pending"
    document.error = None
    document.attempt_count = 0
    # Dropping the run id fences off any worker still holding the old attempt.
    document.ingestion_run_id = None
    document.lease_expires_at = None
    await session.commit()
    # `updated_at` is set by the database on update, so the in-memory value is
    # stale until we read it back.
    await session.refresh(document)
    return DocumentOut.model_validate(document, from_attributes=True)


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> None:
    document = await _get_document(session, document_id)
    storage_key = document.storage_key
    await session.execute(Chunk.__table__.delete().where(Chunk.document_id == document_id))
    await session.delete(document)
    await session.commit()
    if storage_key:
        _remove_files(
            lambda: delete_source(get_settings().storage_root, storage_key), document_id
        )


def _remove_files(action, subject) -> None:
    """Best-effort cleanup after the data is already revoked.

    The row is gone, so the document is unreachable whatever happens here. A
    failure is logged for an operator to sweep, never rolled back into
    resurrecting the record.
    """
    try:
        action()
    except OSError:
        logger.warning("storage cleanup failed for %s", subject, exc_info=False)
