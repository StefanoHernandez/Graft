"""Reading transcripts, and the one thing an owner must not be handed.

The visitor's session id is their capability to resume a conversation on the
public endpoint. An owner reading what was said has no need for it, so it never
leaves the server.
"""
import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from graft.cli import create_admin
from graft.models import Bot, Conversation, Message

PASSWORD = "correct-horse-battery-staple"
SESSION_ID = "s3cret-visitor-session-token-value"


@pytest.fixture
async def auth(db_engine, ready_client):
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    email = f"owner-{uuid.uuid4().hex}@example.test"
    async with maker() as session:
        await create_admin(session, email, PASSWORD)
    resp = await ready_client.post(
        "/auth/jwt/login", data={"username": email, "password": PASSWORD}
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture
async def maker(db_engine):
    return async_sessionmaker(db_engine, expire_on_commit=False)


async def _conversation(maker, *, messages=2, session_id=SESSION_ID):
    async with maker() as session:
        bot = Bot(name="b", widget_key=f"wk_{uuid.uuid4().hex}")
        session.add(bot)
        await session.flush()
        conversation = Conversation(bot_id=bot.id, visitor_session=session_id)
        session.add(conversation)
        await session.flush()
        await session.commit()

    # One commit per message, the way the chat endpoint writes them: rows inserted
    # in a single transaction would share created_at and sort arbitrarily.
    for index in range(messages):
        role = "user" if index % 2 == 0 else "assistant"
        async with maker() as session:
            session.add(Message(
                conversation_id=conversation.id,
                role=role,
                content=f"message {index}",
                status="completed",
                citations={"items": [{"id": "S1", "filename": "manual.pdf", "page": 2}],
                           "grounding": "retrieved"} if role == "assistant" else None,
            ))
            await session.commit()
    return bot, conversation


async def test_anonymous_cannot_read_transcripts(ready_client, maker):
    bot, conversation = await _conversation(maker)
    assert (await ready_client.get(
        f"/api/v1/admin/bots/{bot.id}/conversations")).status_code == 401
    assert (await ready_client.get(
        f"/api/v1/admin/conversations/{conversation.id}")).status_code == 401


async def test_conversations_are_listed_with_their_activity(ready_client, auth, maker):
    bot, _ = await _conversation(maker, messages=3)
    resp = await ready_client.get(f"/api/v1/admin/bots/{bot.id}/conversations", headers=auth)
    body = resp.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["message_count"] == 3
    assert item["last_activity_at"]


async def test_the_visitor_session_id_never_leaves_the_server(ready_client, auth, maker):
    bot, conversation = await _conversation(maker)
    listing = await ready_client.get(
        f"/api/v1/admin/bots/{bot.id}/conversations", headers=auth
    )
    detail = await ready_client.get(
        f"/api/v1/admin/conversations/{conversation.id}", headers=auth
    )
    assert SESSION_ID not in listing.text
    assert SESSION_ID not in detail.text
    # A short handle is enough to tell two transcripts apart.
    assert detail.json()["label"] == SESSION_ID[:8]


async def test_a_transcript_reads_in_order_with_its_citations(ready_client, auth, maker):
    _, conversation = await _conversation(maker, messages=4)
    body = (await ready_client.get(
        f"/api/v1/admin/conversations/{conversation.id}", headers=auth)).json()
    assert [m["role"] for m in body["messages"]] == ["user", "assistant", "user", "assistant"]
    assert [m["content"] for m in body["messages"]] == [f"message {i}" for i in range(4)]
    assert body["messages"][1]["citations"][0]["filename"] == "manual.pdf"
    assert body["messages"][0]["citations"] == []


async def test_an_empty_conversation_is_not_an_error(ready_client, auth, maker):
    _, conversation = await _conversation(maker, messages=0)
    body = (await ready_client.get(
        f"/api/v1/admin/conversations/{conversation.id}", headers=auth)).json()
    assert body["messages"] == []


async def test_conversation_listing_is_paginated(ready_client, auth, maker):
    bot, _ = await _conversation(maker)
    maker_ = maker
    async with maker_() as session:
        for index in range(3):
            session.add(Conversation(bot_id=bot.id, visitor_session=f"other-{index}"))
        await session.commit()
    body = (await ready_client.get(
        f"/api/v1/admin/bots/{bot.id}/conversations?limit=2", headers=auth)).json()
    assert len(body["items"]) == 2
    assert body["total"] == 4


async def test_a_missing_conversation_is_404(ready_client, auth):
    resp = await ready_client.get(
        f"/api/v1/admin/conversations/{uuid.uuid4()}", headers=auth
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "conversation_not_found"
