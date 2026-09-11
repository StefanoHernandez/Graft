import logging
from contextlib import asynccontextmanager

from arq.connections import RedisSettings, create_pool
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import admin, chat, health
from .config import get_settings
from .security.auth import auth_backend, fastapi_users

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Hold one arq pool for the process.

    A Redis that is down must not stop the app from accepting uploads: the
    document is committed either way and the worker's dispatcher sweeps the
    database, so losing the enqueue costs latency, not work.
    """
    app.state.arq = None
    try:
        app.state.arq = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    except Exception:  # noqa: BLE001 - any Redis failure is the same non-fatal case
        logger.warning("redis unavailable at startup; ingestion falls back to the dispatcher")
    yield
    if app.state.arq is not None:
        await app.state.arq.aclose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Graft", lifespan=lifespan)
    if settings.cors_origins:
        # Only for an admin UI served from another origin. The public chat endpoint
        # does its own per-bot origin check: a wildcard there would let any page
        # spend any bot's quota.
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    app.include_router(health.router)
    # Login only: accounts come from `python -m graft.cli create-admin`, never
    # from a public registration route.
    app.include_router(
        fastapi_users.get_auth_router(auth_backend), prefix="/auth/jwt", tags=["auth"]
    )
    app.include_router(admin.router)
    app.include_router(chat.router)
    return app


app = create_app()
