"""Admin API: nothing here is reachable without an active owner.

Every test goes through HTTP, because the guard that matters is the one on the
route, not a helper somewhere below it.
"""
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from graft.cli import create_admin
from graft.models import Bot, Document, User
from graft.security.crypto import decrypt

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "documents"
PASSWORD = "correct-horse-battery-staple"

EMBEDDING_IN = {"provider": "openai_compatible", "model": "text-embedding-3-small",
                "api_key": "sk-secret-value"}
LLM_IN = {"provider": "openai_compatible", "model": "gpt-4o-mini", "api_key": "sk-other-secret"}


@pytest.fixture
async def owner_token(db_engine, ready_client):
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    email = f"owner-{uuid.uuid4().hex}@example.test"
    async with maker() as session:
        await create_admin(session, email, PASSWORD)
    resp = await ready_client.post(
        "/auth/jwt/login", data={"username": email, "password": PASSWORD}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest.fixture
def auth(owner_token):
    return {"Authorization": f"Bearer {owner_token}"}


async def _bot(client, auth, **overrides):
    body = {"name": "Docs bot", "allowed_origins": ["https://example.test"],
            "llm_config": LLM_IN, "embedding_config": EMBEDDING_IN, **overrides}
    resp = await client.post("/api/v1/admin/bots", json=body, headers=auth)
    assert resp.status_code == 201, resp.text
    return resp.json()


# --- access control ----------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/v1/admin/bots"),
        ("post", "/api/v1/admin/bots"),
        ("get", f"/api/v1/admin/bots/{uuid.uuid4()}/documents"),
        ("delete", f"/api/v1/admin/documents/{uuid.uuid4()}"),
    ],
)
async def test_anonymous_is_rejected(ready_client, method, path):
    resp = await getattr(ready_client, method)(path)
    assert resp.status_code == 401


async def test_there_is_no_public_registration_route(ready_client):
    resp = await ready_client.post(
        "/auth/register", json={"email": "x@example.test", "password": "whatever"}
    )
    assert resp.status_code == 404


async def test_a_non_owner_is_forbidden(db_engine, ready_client):
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    email = f"editor-{uuid.uuid4().hex}@example.test"
    async with maker() as session:
        await create_admin(session, email, PASSWORD, role="editor")
    login = await ready_client.post(
        "/auth/jwt/login", data={"username": email, "password": PASSWORD}
    )
    token = login.json()["access_token"]
    resp = await ready_client.get(
        "/api/v1/admin/bots", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 403


async def test_a_deactivated_owner_is_rejected(db_engine, ready_client, owner_token, auth):
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        user = (await session.execute(select(User))).scalars().first()
        user.is_active = False
        await session.commit()
    resp = await ready_client.get("/api/v1/admin/bots", headers=auth)
    assert resp.status_code == 401


async def test_bootstrap_refuses_a_second_owner(db_engine):
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        await create_admin(session, "first@example.test", PASSWORD)
        with pytest.raises(ValueError):
            await create_admin(session, "second@example.test", PASSWORD)


async def test_two_concurrent_bootstraps_still_produce_one_owner(db_engine):
    """The advisory lock, not luck, is what makes this safe."""
    import asyncio

    maker = async_sessionmaker(db_engine, expire_on_commit=False)

    async def bootstrap(email):
        async with maker() as session:
            try:
                await create_admin(session, email, PASSWORD)
                return "created"
            except ValueError:
                return "refused"

    results = await asyncio.gather(
        bootstrap("a@example.test"), bootstrap("b@example.test")
    )
    assert sorted(results) == ["created", "refused"]
    async with maker() as session:
        owners = (await session.execute(select(User).where(User.role == "owner"))).scalars().all()
    assert len(owners) == 1


# --- bots --------------------------------------------------------------------


async def test_create_bot_generates_a_widget_key_and_hides_api_keys(ready_client, auth):
    bot = await _bot(ready_client, auth)
    assert len(bot["widget_key"]) >= 32
    assert bot["embedding_config"]["has_api_key"] is True
    assert "api_key" not in bot["embedding_config"]
    assert "sk-secret-value" not in str(bot)


async def test_api_keys_are_encrypted_before_they_reach_the_database(
    db_engine, ready_client, auth
):
    bot = await _bot(ready_client, auth)
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        stored = (await session.get(Bot, uuid.UUID(bot["id"]))).embedding_config
    assert stored["api_key"] != "sk-secret-value"
    assert decrypt(stored["api_key"]) == "sk-secret-value"


async def test_list_bots_is_paginated(ready_client, auth):
    for index in range(3):
        await _bot(ready_client, auth, name=f"bot-{index}")
    resp = await ready_client.get("/api/v1/admin/bots?limit=2", headers=auth)
    body = resp.json()
    assert len(body["items"]) == 2
    assert body["total"] >= 3
    too_big = await ready_client.get("/api/v1/admin/bots?limit=500", headers=auth)
    assert too_big.status_code == 422


async def test_patch_keeps_an_omitted_key_and_clears_an_explicit_null(
    db_engine, ready_client, auth
):
    bot = await _bot(ready_client, auth)
    maker = async_sessionmaker(db_engine, expire_on_commit=False)

    kept = await ready_client.patch(
        f"/api/v1/admin/bots/{bot['id']}",
        json={"llm_config": {"provider": "openai_compatible", "model": "gpt-4o"}},
        headers=auth,
    )
    assert kept.status_code == 200
    assert kept.json()["llm_config"]["has_api_key"] is True
    async with maker() as session:
        stored = (await session.get(Bot, uuid.UUID(bot["id"]))).llm_config
        assert decrypt(stored["api_key"]) == "sk-other-secret"

    cleared = await ready_client.patch(
        f"/api/v1/admin/bots/{bot['id']}",
        json={"llm_config": {"provider": "openai_compatible", "model": "gpt-4o",
                             "api_key": None}},
        headers=auth,
    )
    assert cleared.json()["llm_config"]["has_api_key"] is False


async def test_embedding_config_locks_once_documents_exist(ready_client, auth):
    bot = await _bot(ready_client, auth)
    await _upload(ready_client, auth, bot["id"])
    resp = await ready_client.patch(
        f"/api/v1/admin/bots/{bot['id']}",
        json={"embedding_config": {"provider": "mistral", "model": "mistral-embed"}},
        headers=auth,
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "embedding_config_locked"


async def test_rotating_only_the_api_key_is_still_allowed(ready_client, auth):
    bot = await _bot(ready_client, auth)
    await _upload(ready_client, auth, bot["id"])
    resp = await ready_client.patch(
        f"/api/v1/admin/bots/{bot['id']}",
        json={"embedding_config": {**{k: v for k, v in EMBEDDING_IN.items() if k != "api_key"},
                                   "api_key": "sk-rotated"}},
        headers=auth,
    )
    assert resp.status_code == 200


# --- documents ---------------------------------------------------------------


async def _upload(client, auth, bot_id, name="notes.txt", mime="text/plain", data=b"hello"):
    return await client.post(
        f"/api/v1/admin/bots/{bot_id}/documents",
        files={"file": (name, data, mime)},
        headers=auth,
    )


async def test_upload_stores_the_original_and_queues_the_document(
    db_engine, ready_client, auth, tmp_path
):
    bot = await _bot(ready_client, auth)
    resp = await _upload(ready_client, auth, bot["id"], data=b"real content")
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["status"] == "pending"

    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        doc = await session.get(Document, uuid.UUID(body["id"]))
        assert doc.storage_key == f"{bot['id']}/{body['id']}/source"
        assert doc.source_sha256
    from graft.config import get_settings
    from graft.ingestion.storage import read_source
    assert read_source(get_settings().storage_root, doc.storage_key) == b"real content"


async def test_a_hostile_filename_never_reaches_the_path(ready_client, auth):
    bot = await _bot(ready_client, auth)
    resp = await _upload(ready_client, auth, bot["id"], name="../../etc/passwd.txt")
    assert resp.status_code == 202
    assert resp.json()["filename"] == "../../etc/passwd.txt"  # kept as metadata only


async def test_upload_rejects_an_unsupported_type(ready_client, auth):
    bot = await _bot(ready_client, auth)
    resp = await _upload(ready_client, auth, bot["id"], name="x.exe",
                         mime="application/octet-stream")
    assert resp.status_code == 415


async def test_upload_rejects_a_file_over_the_ceiling(ready_client, auth, monkeypatch):
    from graft.api import admin

    monkeypatch.setattr(admin, "MAX_UPLOAD_BYTES", 16)
    bot = await _bot(ready_client, auth)
    resp = await _upload(ready_client, auth, bot["id"], data=b"x" * 64)
    assert resp.status_code == 413


async def test_upload_to_a_missing_bot_is_404(ready_client, auth):
    resp = await _upload(ready_client, auth, uuid.uuid4())
    assert resp.status_code == 404


async def test_documents_are_listed_with_status_and_chunk_count(ready_client, auth):
    bot = await _bot(ready_client, auth)
    await _upload(ready_client, auth, bot["id"])
    resp = await ready_client.get(f"/api/v1/admin/bots/{bot['id']}/documents", headers=auth)
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["status"] == "pending"
    assert body["items"][0]["chunk_count"] == 0


async def test_retry_only_applies_to_a_failed_document(db_engine, ready_client, auth):
    bot = await _bot(ready_client, auth)
    created = (await _upload(ready_client, auth, bot["id"])).json()
    busy = await ready_client.post(
        f"/api/v1/admin/documents/{created['id']}/retry", headers=auth
    )
    assert busy.status_code == 409

    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        doc = await session.get(Document, uuid.UUID(created["id"]))
        doc.status = "failed"
        doc.error = "provider_auth"
        doc.attempt_count = 3
        doc.ingestion_run_id = uuid.uuid4()
        await session.commit()

    resp = await ready_client.post(
        f"/api/v1/admin/documents/{created['id']}/retry", headers=auth
    )
    assert resp.status_code == 202
    async with maker() as session:
        doc = await session.get(Document, uuid.UUID(created["id"]))
        assert doc.status == "pending"
        assert doc.error is None
        assert doc.attempt_count == 0
        assert doc.ingestion_run_id is None


async def test_delete_document_revokes_the_row_then_the_file(db_engine, ready_client, auth):
    from graft.config import get_settings
    from graft.ingestion.storage import source_path

    bot = await _bot(ready_client, auth)
    created = (await _upload(ready_client, auth, bot["id"])).json()
    path = source_path(get_settings().storage_root, f"{bot['id']}/{created['id']}/source")
    assert path.exists()

    resp = await ready_client.delete(f"/api/v1/admin/documents/{created['id']}", headers=auth)
    assert resp.status_code == 204
    assert not path.exists()
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        assert await session.get(Document, uuid.UUID(created["id"])) is None


async def test_delete_bot_removes_its_documents(db_engine, ready_client, auth):
    bot = await _bot(ready_client, auth)
    created = (await _upload(ready_client, auth, bot["id"])).json()
    resp = await ready_client.delete(f"/api/v1/admin/bots/{bot['id']}", headers=auth)
    assert resp.status_code == 204
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        assert await session.get(Document, uuid.UUID(created["id"])) is None


# --- provider test -----------------------------------------------------------


async def test_provider_test_reports_codes_not_messages(ready_client, auth, monkeypatch):
    from graft.api import admin
    from graft.providers.base import ProviderError

    class _OkLLM:
        async def stream_chat(self, messages, *, model, **kwargs):
            yield "pong"

        async def aclose(self):
            return None

    class _BadEmbedder:
        async def embed(self, texts, *, model):
            raise ProviderError("provider_auth", retryable=False)

        async def aclose(self):
            return None

    monkeypatch.setattr(admin, "build_llm", lambda config, **kw: _OkLLM())
    monkeypatch.setattr(admin, "build_embedder", lambda config, **kw: _BadEmbedder())
    bot = await _bot(ready_client, auth)
    resp = await ready_client.post(
        f"/api/v1/admin/bots/{bot['id']}/provider/test", headers=auth
    )
    body = resp.json()
    assert body["llm"] == {"ok": True, "code": None}
    assert body["embedding"] == {"ok": False, "code": "provider_auth"}


# --- handing work to the worker ----------------------------------------------


async def test_upload_hints_the_worker(ready_client, auth):
    from graft.main import app

    class _Pool:
        def __init__(self):
            self.jobs = []

        async def enqueue_job(self, name, *args, **kwargs):
            self.jobs.append((name, args, kwargs))
            return object()

    pool = _Pool()
    app.state.arq = pool
    try:
        bot = await _bot(ready_client, auth)
        created = (await _upload(ready_client, auth, bot["id"])).json()
    finally:
        app.state.arq = None
    assert pool.jobs[0][0] == "ingest_job"
    assert pool.jobs[0][1] == (created["id"],)
    assert pool.jobs[0][2]["_job_id"] == f"ingest:{created['id']}"


async def test_retry_hints_the_worker_immediately(db_engine, ready_client, auth):
    """Otherwise the operator watches nothing happen until the next sweep."""
    from graft.main import app

    class _Pool:
        def __init__(self):
            self.jobs = []

        async def enqueue_job(self, name, *args, **kwargs):
            self.jobs.append(args)
            return object()

    bot = await _bot(ready_client, auth)
    created = (await _upload(ready_client, auth, bot["id"])).json()
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        doc = await session.get(Document, uuid.UUID(created["id"]))
        doc.status = "failed"
        await session.commit()

    pool = _Pool()
    app.state.arq = pool
    try:
        resp = await ready_client.post(
            f"/api/v1/admin/documents/{created['id']}/retry", headers=auth
        )
    finally:
        app.state.arq = None
    assert resp.status_code == 202
    assert pool.jobs == [(created["id"],)]


async def test_upload_survives_an_unreachable_redis(db_engine, ready_client, auth):
    """The row is the work list: a queue outage delays ingestion, it does not lose it."""
    from graft.main import app

    class _DeadPool:
        async def enqueue_job(self, *args, **kwargs):
            raise ConnectionError("redis is down")

    app.state.arq = _DeadPool()
    try:
        bot = await _bot(ready_client, auth)
        resp = await _upload(ready_client, auth, bot["id"])
    finally:
        app.state.arq = None
    assert resp.status_code == 202
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        assert (await session.get(Document, uuid.UUID(resp.json()["id"]))).status == "pending"
