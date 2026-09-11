from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import admin, health
from .config import get_settings
from .security.auth import auth_backend, fastapi_users


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Graft")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins or ["*"],
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
    return app


app = create_app()
