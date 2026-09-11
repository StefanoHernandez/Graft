"""Readiness is what the worker waits on, so it has to fail when a dependency is.

Liveness lives in the unit tier; this file only covers the probe that gates a
deploy.
"""
from pathlib import Path

import pytest


class _Pool:
    def __init__(self, ok=True):
        self.ok = ok

    async def ping(self):
        if not self.ok:
            raise ConnectionError("redis is down")
        return True


@pytest.fixture(autouse=True)
def storage(tmp_path, monkeypatch):
    from graft.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    return tmp_path


async def test_ready_when_every_dependency_answers(ready_client):
    from graft.main import app

    app.state.arq = _Pool()
    try:
        resp = await ready_client.get("/health/ready")
    finally:
        app.state.arq = None
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    assert body["checks"] == {"database": "ok", "redis": "ok", "storage": "ok"}


async def test_not_ready_without_a_queue(ready_client):
    from graft.main import app

    app.state.arq = None
    resp = await ready_client.get("/health/ready")
    assert resp.status_code == 503
    assert resp.json()["checks"]["redis"] == "not connected"


async def test_not_ready_when_redis_refuses(ready_client):
    from graft.main import app

    app.state.arq = _Pool(ok=False)
    try:
        resp = await ready_client.get("/health/ready")
    finally:
        app.state.arq = None
    assert resp.status_code == 503
    assert resp.json()["checks"]["redis"] == "unreachable"


async def test_not_ready_when_the_uploads_volume_is_not_mounted(ready_client, monkeypatch):
    from graft.config import get_settings
    from graft.main import app

    monkeypatch.setattr(get_settings(), "storage_root", Path("/nonexistent-graft-volume"))
    app.state.arq = _Pool()
    try:
        resp = await ready_client.get("/health/ready")
    finally:
        app.state.arq = None
    assert resp.status_code == 503
    assert resp.json()["checks"]["storage"] == "missing"
