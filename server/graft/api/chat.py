"""The public chat endpoint.

Order matters more than anything else in this file: every access and quota check
runs **before** a provider is touched, because the cheapest way to spend someone
else's budget is an endpoint that calls a model first and asks questions later.

Transport is SSE over POST, so the browser side uses fetch + ReadableStream
rather than EventSource.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import secrets
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_session
from ..models import Bot, Conversation, Message
from ..providers.base import ProviderError
from ..providers.config import EmbeddingConfig, LLMConfig
from ..providers.factory import build_embedder, build_llm
from ..providers.fingerprint import embedding_fingerprint
from ..rag.service import answer_question
from ..security.origins import origin_allowed
from ..security.rate_limit import acquire_slot, check_rate, release_slot

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["chat"])

MAX_MESSAGE_CHARS = 2000
HISTORY_MESSAGES = 6
HISTORY_CHARS = 8000
SESSION_ID_BYTES = 32  # 256 bits of entropy: the session id is the visitor's capability

RATE_PER_IP = 10
RATE_PER_BOT = 100
RATE_WINDOW_SECONDS = 60
CONCURRENT_GENERATIONS_PER_BOT = 2
SLOT_TTL_SECONDS = 120
HEARTBEAT_SECONDS = 15


class ChatRequest(BaseModel):
    bot_key: str = Field(min_length=1, max_length=128)
    session_id: str | None = Field(default=None, max_length=128)
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)


def encode_sse(event: str, payload: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n".encode()


@router.options("/chat")
async def chat_preflight(
    request: Request,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> Response:
    """Answer a preflight for any origin some bot allows.

    A preflight carries no body, so the bot is unknown here; the exact bot is
    checked on the POST. This only decides whether the browser may ask.
    """
    origin = request.headers.get("origin")
    if not await _origin_known(session, origin):
        return Response(status_code=status.HTTP_403_FORBIDDEN, headers={"Vary": "Origin"})
    return Response(status_code=status.HTTP_204_NO_CONTENT, headers=_cors_headers(origin))


@router.post("/chat")
async def chat(
    request: Request,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> Response:
    request_id = str(uuid.uuid4())
    origin = request.headers.get("origin")

    body = await _parse(request)
    if body is None:
        return _refuse(status.HTTP_400_BAD_REQUEST, "invalid_request", request_id, origin)

    bot = (
        await session.execute(select(Bot).where(Bot.widget_key == body.bot_key))
    ).scalar_one_or_none()
    if bot is None:
        return _refuse(status.HTTP_404_NOT_FOUND, "bot_not_found", request_id, origin)
    if not origin_allowed(origin, list(bot.allowed_origins or [])):
        return _refuse(status.HTTP_403_FORBIDDEN, "origin_not_allowed", request_id, origin)

    redis = getattr(request.app.state, "arq", None)
    if redis is None:
        # Fail closed: without Redis there is no limit, and an unlimited public
        # endpoint is an unlimited provider bill.
        return _refuse(status.HTTP_503_SERVICE_UNAVAILABLE, "dependency_unavailable",
                       request_id, origin)

    try:
        within_limits = await _within_limits(redis, bot.id, _client_ip(request))
    except Exception:  # noqa: BLE001 - a broken limiter is the same as no limiter
        logger.warning("rate limiting unavailable for bot %s", bot.id)
        return _refuse(status.HTTP_503_SERVICE_UNAVAILABLE, "dependency_unavailable",
                       request_id, origin)
    if not within_limits:
        return _refuse(status.HTTP_429_TOO_MANY_REQUESTS, "rate_limited", request_id, origin)

    session_id = body.session_id or secrets.token_urlsafe(SESSION_ID_BYTES)
    conversation = await _conversation(session, bot.id, session_id)

    # One live request per conversation, so two tabs cannot interleave turns into
    # a history that then reads as nonsense.
    if not await acquire_slot(redis, f"chat:conv:{conversation.id}", limit=1,
                              ttl=SLOT_TTL_SECONDS, token=request_id):
        return _refuse(status.HTTP_409_CONFLICT, "conversation_busy", request_id, origin)
    if not await acquire_slot(redis, f"chat:gen:{bot.id}", limit=CONCURRENT_GENERATIONS_PER_BOT,
                              ttl=SLOT_TTL_SECONDS, token=request_id):
        await release_slot(redis, f"chat:conv:{conversation.id}", request_id)
        return _refuse(status.HTTP_429_TOO_MANY_REQUESTS, "rate_limited", request_id, origin)

    try:
        embedder = build_embedder(EmbeddingConfig(**bot.embedding_config))
        llm = build_llm(LLMConfig(**bot.llm_config))
        fingerprint = embedding_fingerprint(EmbeddingConfig(**bot.embedding_config))
    except (ProviderError, TypeError, ValidationError):
        await _release(redis, conversation.id, bot.id, request_id)
        return _refuse(status.HTTP_503_SERVICE_UNAVAILABLE, "provider_config",
                       request_id, origin)

    history = await _history(session, conversation.id)
    user_message = Message(
        conversation_id=conversation.id, role="user", content=body.message,
        request_id=uuid.UUID(request_id),
        # Starts as cancelled: if the process dies mid-answer, the row already
        # says this attempt never completed.
        status="cancelled",
    )
    session.add(user_message)
    await session.commit()

    stream = _stream(
        session=session, redis=redis, bot=bot, conversation=conversation,
        user_message=user_message, embedder=embedder, llm=llm, question=body.message,
        history=history, fingerprint=fingerprint, request_id=request_id,
        session_id=session_id,
    )
    return StreamingResponse(
        _with_heartbeat(stream),
        media_type="text/event-stream",
        headers={
            **_cors_headers(origin),
            "Cache-Control": "no-cache",
            # Tells nginx not to buffer, which would hold every token until the end.
            "X-Accel-Buffering": "no",
        },
    )


async def _stream(
    *, session, redis, bot, conversation, user_message, embedder, llm, question,
    history, fingerprint, request_id, session_id,
) -> AsyncIterator[bytes]:
    yield encode_sse("meta", {"session_id": session_id, "request_id": request_id})
    retrieval = bot.retrieval_config or {}
    try:
        async for event in answer_question(
            session,
            bot=bot,
            embedder=embedder,
            llm=llm,
            question=question,
            history=history,
            fingerprint=fingerprint,
            embedding_model=bot.embedding_config["model"],
            chat_model=bot.llm_config["model"],
            top_k=retrieval.get("top_k", 5),
            min_score=retrieval.get("min_score", 0.5),
        ):
            if event["event"] == "done":
                await _persist_answer(session, conversation, user_message, event["data"])
            elif event["event"] == "error":
                await _mark_failed(session, user_message)
            yield encode_sse(event["event"], event["data"])
    except asyncio.CancelledError:
        # The visitor left. Nothing is persisted as an answer.
        raise
    except Exception:
        logger.exception("chat stream failed for request %s", request_id)
        await _mark_failed(session, user_message)
        yield encode_sse("error", {"code": "internal_error", "request_id": request_id})
    finally:
        await _release(redis, conversation.id, bot.id, request_id)
        for client in (embedder, llm):
            if hasattr(client, "aclose"):
                with contextlib.suppress(Exception):
                    await client.aclose()


async def _with_heartbeat(stream: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
    """Emit an SSE comment while the model is thinking.

    Without it a proxy or a phone radio can drop a connection that has been quiet
    for a minute, which looks to the visitor like the answer vanished.
    """
    iterator = stream.__aiter__()
    pending: asyncio.Task[bytes] | None = None
    try:
        while True:
            pending = asyncio.ensure_future(iterator.__anext__())
            while True:
                done, _ = await asyncio.wait({pending}, timeout=HEARTBEAT_SECONDS)
                if done:
                    break
                yield b": keep-alive\n\n"
            try:
                yield pending.result()
            except StopAsyncIteration:
                return
    finally:
        # The visitor can leave while we are parked on a keep-alive. Cancelling
        # hands CancelledError to `_stream`, so its finally releases the Redis
        # slots now instead of leaving them to expire, and no task is left behind.
        if pending is not None and not pending.done():
            pending.cancel()


async def _parse(request: Request) -> ChatRequest | None:
    try:
        payload = await request.json()
        return ChatRequest(**payload)
    except (ValidationError, ValueError, TypeError):
        return None


async def _origin_known(session: AsyncSession, origin: str | None) -> bool:
    if origin is None:
        return False
    rows = (await session.execute(select(Bot.allowed_origins))).scalars().all()
    return any(origin_allowed(origin, list(entry or [])) for entry in rows)


async def _within_limits(redis, bot_id: uuid.UUID, client_ip: str) -> bool:
    per_ip = await check_rate(redis, f"chat:rate:{bot_id}:{client_ip}",
                              limit=RATE_PER_IP, window=RATE_WINDOW_SECONDS)
    per_bot = await check_rate(redis, f"chat:rate:{bot_id}",
                               limit=RATE_PER_BOT, window=RATE_WINDOW_SECONDS)
    return per_ip and per_bot


def _client_ip(request: Request) -> str:
    """Trust `X-Forwarded-For` only from proxies the operator named.

    Otherwise any visitor could rotate the header and get a fresh quota each time.
    """
    peer = request.client.host if request.client else "unknown"
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded and peer in get_settings().trusted_proxy_ips:
        return forwarded.split(",")[0].strip()
    return peer


async def _conversation(session: AsyncSession, bot_id: uuid.UUID, session_id: str) -> Conversation:
    conversation = (
        await session.execute(
            select(Conversation).where(
                Conversation.bot_id == bot_id, Conversation.visitor_session == session_id
            )
        )
    ).scalar_one_or_none()
    if conversation is not None:
        return conversation
    conversation = Conversation(bot_id=bot_id, visitor_session=session_id)
    session.add(conversation)
    await session.commit()
    return conversation


async def _history(session: AsyncSession, conversation_id: uuid.UUID) -> list[dict]:
    """The last completed turns, read from the database — never from the request."""
    rows = (
        await session.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id, Message.status == "completed")
            .order_by(Message.created_at.desc(), Message.id)
            .limit(HISTORY_MESSAGES)
        )
    ).scalars().all()
    history: list[dict] = []
    used = 0
    for message in rows:
        if used + len(message.content) > HISTORY_CHARS:
            break
        history.append({"role": message.role, "content": message.content})
        used += len(message.content)
    history.reverse()
    return history


async def _persist_answer(session, conversation, user_message, data: dict) -> None:
    """One transaction: the answer exists and the attempt completed, or neither."""
    session.add(Message(
        conversation_id=conversation.id, role="assistant", content=data["answer"],
        citations={"items": data["citations"], "grounding": data["grounding"]},
        request_id=user_message.request_id, status="completed",
    ))
    user_message.status = "completed"
    await session.commit()


async def _mark_failed(session, user_message) -> None:
    user_message.status = "failed"
    await session.commit()


async def _release(redis, conversation_id, bot_id, request_id) -> None:
    with contextlib.suppress(Exception):
        await release_slot(redis, f"chat:conv:{conversation_id}", request_id)
        await release_slot(redis, f"chat:gen:{bot_id}", request_id)


def _cors_headers(origin: str | None) -> dict[str, str]:
    headers = {"Vary": "Origin"}
    if origin:
        headers["Access-Control-Allow-Origin"] = origin
        headers["Access-Control-Allow-Headers"] = "content-type"
        headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    return headers


def _refuse(code: int, reason: str, request_id: str, origin: str | None) -> JSONResponse:
    """Errors before the stream are plain JSON: the SSE contract has not started yet."""
    return JSONResponse(
        status_code=code,
        content={"error": {"code": reason, "request_id": request_id}},
        headers=_cors_headers(origin),
    )


__all__ = ["encode_sse", "router"]
