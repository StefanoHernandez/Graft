from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import health
from .config import get_settings


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
    return app


app = create_app()
