"""Liveness and readiness.

Readiness is what the worker waits on and what a load balancer should watch, so
it checks the three things an unready instance is actually missing: the database,
the queue, and the directory the originals live in. A probe that only proves the
process is running would let the worker start against a half-configured host.
"""
import os

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_session

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness: the process answers. Deliberately touches nothing else."""
    return {"status": "ok"}


@router.get("/health/ready")
async def ready(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict:
    checks = {
        "database": await _check_database(session),
        "redis": await _check_redis(request),
        "storage": _check_storage(),
    }
    failed = [name for name, outcome in checks.items() if outcome != "ok"]
    if failed:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "not ready", "checks": checks}
    return {"status": "ready", "checks": checks}


async def _check_database(session: AsyncSession) -> str:
    try:
        await session.execute(text("SELECT 1"))
        return "ok"
    except Exception:  # noqa: BLE001 - the reason belongs in the logs, not the probe
        return "unreachable"


async def _check_redis(request: Request) -> str:
    pool = getattr(request.app.state, "arq", None)
    if pool is None:
        return "not connected"
    try:
        await pool.ping()
        return "ok"
    except Exception:  # noqa: BLE001
        return "unreachable"


def _check_storage() -> str:
    """The originals directory has to be writable, not merely configured.

    A worker that starts against an unmounted volume fails one document at a
    time instead of failing to start.
    """
    root = get_settings().storage_root
    if not root.is_dir():
        return "missing"
    if not os.access(root, os.W_OK):
        return "not writable"
    return "ok"
