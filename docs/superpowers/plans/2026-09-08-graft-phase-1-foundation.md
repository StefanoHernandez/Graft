# Graft — Phase 1: Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the Graft backend skeleton — a runnable FastAPI service with Postgres+pgvector and Redis via Docker Compose, an async DB layer, Alembic migrations for the core schema, and the provider-key encryption utility.

**Architecture:** Modular monolith in Python/FastAPI. This phase delivers only the foundation: config, app factory, health checks, async SQLAlchemy 2.0 engine/session, the non-vector core tables (users, bots, bot_members, documents, conversations, messages), the pgvector extension enabled for later phases, and a Fernet-based encryption helper for provider API keys. No LLM, RAG, ingestion, auth wiring, or widget yet.

**Tech Stack:** Python 3.12, uv, FastAPI, uvicorn, SQLAlchemy 2.0 (async, asyncpg), Alembic (sync via psycopg), pgvector, pydantic-settings, fastapi-users (User base table only), cryptography (Fernet), pytest + pytest-asyncio + httpx + testcontainers, Postgres image `pgvector/pgvector:pg16`, Redis `redis:7-alpine`.

**Spec:** `docs/superpowers/specs/2026-09-08-graft-design.md`

## Global Constraints

- **Python** `>=3.12`.
- **Package/dep manager**: `uv`. All commands run as `uv run <cmd>` from `server/`.
- **DB drivers**: runtime async = `asyncpg` (`postgresql+asyncpg://`); Alembic + tests sync = `psycopg` v3 (`postgresql+psycopg://`).
- **Postgres image**: `pgvector/pgvector:pg16` (dev, prod, and tests via testcontainers).
- **All models** inherit one shared `Base` (a single `DeclarativeBase`) so Alembic sees one metadata and fastapi-users shares it.
- **Primary keys**: UUID (`uuid.uuid4`), column name `id`.
- **Timestamps**: every table has `created_at` and `updated_at` (server-side `now()`).
- **No `chunks` table in this phase** — vector storage is designed in Phase 3 (spec §6.1).
- **Provider secrets** are never stored in plaintext — always via `graft.security.crypto`.
- Repo layout: Python backend lives under `server/`; `widget/` and `admin/` are added in later phases.

---

### Task 1: Project scaffolding + `/health`

**Files:**
- Create: `server/pyproject.toml`
- Create: `server/graft/__init__.py`
- Create: `server/graft/config.py`
- Create: `server/graft/main.py`
- Create: `server/graft/api/__init__.py`
- Create: `server/graft/api/health.py`
- Create: `server/tests/__init__.py`
- Create: `server/tests/conftest.py`
- Test: `server/tests/test_health.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces:
  - `graft.config.Settings` (pydantic-settings) with fields `database_url: str`, `redis_url: str`, `jwt_secret: str`, `encryption_key: str`, `cors_origins: list[str]`, `app_env: str`.
  - `graft.config.get_settings() -> Settings` (lru_cache'd).
  - `graft.main.create_app() -> FastAPI` and module-level `app = create_app()`.
  - `GET /health` → `200 {"status": "ok"}`.
  - pytest fixture `client` (httpx `AsyncClient` bound to `app`) in `conftest.py`.

- [ ] **Step 1: Write `server/pyproject.toml`**

```toml
[project]
name = "graft-server"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "pydantic-settings>=2.4",
    "sqlalchemy[asyncio]>=2.0.30",
    "asyncpg>=0.29",
    "psycopg[binary]>=3.2",
    "alembic>=1.13",
    "pgvector>=0.3",
    "fastapi-users[sqlalchemy]>=13",
    "cryptography>=43",
]

[dependency-groups]
dev = [
    "pytest>=8",
    "pytest-asyncio>=0.24",
    "httpx>=0.27",
    "testcontainers[postgres]>=4.8",
    "ruff>=0.6",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
line-length = 100

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["graft"]
```

- [ ] **Step 2: Write the failing test** — `server/tests/test_health.py`

```python
async def test_health_ok(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
```

- [ ] **Step 3: Write `conftest.py` client fixture** — `server/tests/conftest.py`

```python
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from graft.main import app


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
```

- [ ] **Step 4: Run the test to verify it fails**

Run: `cd server && uv run pytest tests/test_health.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'graft.main'` (or import error).

- [ ] **Step 5: Implement `config.py`**

```python
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://graft:graft@localhost:5432/graft"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str = "change-me"
    encryption_key: str = ""  # Fernet key (urlsafe base64, 32 bytes)
    cors_origins: list[str] = []
    app_env: str = "dev"


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 6: Implement `api/health.py`**

```python
from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 7: Implement `main.py`** (and empty `graft/__init__.py`, `graft/api/__init__.py`, `tests/__init__.py`)

```python
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
```

- [ ] **Step 8: Run the test to verify it passes**

Run: `cd server && uv run pytest tests/test_health.py -v`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add server/
git commit -m "feat(server): scaffold FastAPI app with health endpoint"
```

---

### Task 2: Docker Compose (app + db + redis)

**Files:**
- Create: `server/Dockerfile`
- Create: `server/entrypoint.sh`
- Create: `docker-compose.yml` (repo root)
- Create: `.env.example` (repo root)
- Create: `.gitignore` (repo root)

**Interfaces:**
- Consumes: `graft.main:app` from Task 1.
- Produces: a `docker compose` stack with services `db`, `redis`, `app`; `app` serves `/health` on port 8000. `entrypoint.sh` runs `alembic upgrade head` then uvicorn (migrations wired in Task 5; the command is present now and is a no-op until the first migration exists).

- [ ] **Step 1: Write `.gitignore`**

```gitignore
__pycache__/
*.pyc
.venv/
.env
server/.venv/
```

- [ ] **Step 2: Write `.env.example`**

```dotenv
DATABASE_URL=postgresql+asyncpg://graft:graft@db:5432/graft
REDIS_URL=redis://redis:6379/0
JWT_SECRET=replace-with-a-long-random-string
ENCRYPTION_KEY=replace-with-a-fernet-key
CORS_ORIGINS=[]
APP_ENV=dev
```

- [ ] **Step 3: Write `server/Dockerfile`**

```dockerfile
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml ./
RUN uv sync --no-dev --no-install-project
COPY . .
RUN uv sync --no-dev
RUN chmod +x entrypoint.sh
EXPOSE 8000
ENTRYPOINT ["./entrypoint.sh"]
```

- [ ] **Step 4: Write `server/entrypoint.sh`**

```bash
#!/usr/bin/env bash
set -e
uv run alembic upgrade head || echo "no migrations yet"
exec uv run uvicorn graft.main:app --host 0.0.0.0 --port 8000
```

- [ ] **Step 5: Write `docker-compose.yml`**

```yaml
services:
  db:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: graft
      POSTGRES_PASSWORD: graft
      POSTGRES_DB: graft
    ports:
      - "5432:5432"
    volumes:
      - graft_db:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U graft"]
      interval: 5s
      timeout: 3s
      retries: 10

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  app:
    build: ./server
    env_file: .env
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_started
    ports:
      - "8000:8000"

volumes:
  graft_db:
```

- [ ] **Step 6: Validate compose config**

Run: `docker compose config -q`
Expected: no output, exit code 0 (compose file is valid).

- [ ] **Step 7: Commit**

```bash
git add server/Dockerfile server/entrypoint.sh docker-compose.yml .env.example .gitignore
git commit -m "feat(infra): docker-compose stack (app + pgvector + redis)"
```

---

### Task 3: Async DB engine, session, and test container

**Files:**
- Create: `server/graft/db.py`
- Modify: `server/tests/conftest.py`
- Test: `server/tests/test_db.py`

**Interfaces:**
- Consumes: `graft.config.get_settings`.
- Produces:
  - `graft.db.get_engine() -> AsyncEngine` (lru_cache'd).
  - `graft.db.get_sessionmaker() -> async_sessionmaker[AsyncSession]` (lru_cache'd).
  - `graft.db.get_session() -> AsyncIterator[AsyncSession]` — FastAPI dependency.
  - conftest fixtures: `pg` (session-scoped `PostgresContainer`, exposes `sync_url` and `async_url`), `db_engine`, `db_session`.

- [ ] **Step 1: Write the failing test** — `server/tests/test_db.py`

```python
from sqlalchemy import text


async def test_db_select_one(db_session):
    result = await db_session.execute(text("SELECT 1"))
    assert result.scalar_one() == 1
```

- [ ] **Step 2: Add DB fixtures to `conftest.py`** (append)

```python
import os

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer


@pytest.fixture(scope="session")
def pg():
    with PostgresContainer("pgvector/pgvector:pg16", username="graft",
                           password="graft", dbname="graft") as container:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(5432)
        base = f"graft:graft@{host}:{port}/graft"
        container.sync_url = f"postgresql+psycopg://{base}"
        container.async_url = f"postgresql+asyncpg://{base}"
        yield container


@pytest_asyncio.fixture
async def db_engine(pg):
    engine = create_async_engine(pg.async_url)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        yield session
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd server && uv run pytest tests/test_db.py -v`
Expected: FAIL — `graft/db.py` not needed by this test yet, but fixture wiring must work; if `testcontainers`/Docker missing it errors here. With Docker present it should now PASS (the test uses only fixtures). If it PASSES, that is acceptable — proceed to create `db.py` for app use in Step 4.

- [ ] **Step 4: Implement `graft/db.py`**

```python
from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .config import get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session:
        yield session
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd server && uv run pytest tests/test_db.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add server/graft/db.py server/tests/conftest.py server/tests/test_db.py
git commit -m "feat(server): async DB engine/session + pgvector test container"
```

---

### Task 4: Core models (users, bots, bot_members, documents, conversations, messages)

**Files:**
- Create: `server/graft/models/__init__.py`
- Create: `server/graft/models/base.py`
- Create: `server/graft/models/user.py`
- Create: `server/graft/models/bot.py`
- Create: `server/graft/models/document.py`
- Create: `server/graft/models/conversation.py`
- Test: `server/tests/test_models.py`

**Interfaces:**
- Consumes: shared `Base`.
- Produces (importable from `graft.models`):
  - `Base` — the single `DeclarativeBase`.
  - `User` (fastapi-users UUID base + `role: str` default `"viewer"`).
  - `Bot(id, name, widget_key, allowed_origins: list[str], llm_config: dict, embedding_config: dict, system_prompt: str, theme: dict, retrieval_config: dict, created_at, updated_at)`.
  - `BotMember(id, user_id, bot_id, created_at, updated_at)` with unique `(user_id, bot_id)`.
  - `Document(id, bot_id, filename, mime_type, status: str default "pending", error: str | None, chunk_count: int default 0, created_at, updated_at)`.
  - `Conversation(id, bot_id, visitor_session, started_at, created_at, updated_at)`.
  - `Message(id, conversation_id, role, content, citations: dict | None, created_at, updated_at)`.

- [ ] **Step 1: Write the failing test** — `server/tests/test_models.py`

```python
import uuid

from sqlalchemy import select

from graft.models import Base, Bot


async def test_bot_roundtrip(db_engine):
    async with db_engine.begin() as conn:
        await conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
        await conn.run_sync(Base.metadata.create_all)

    from sqlalchemy.ext.asyncio import async_sessionmaker

    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        bot = Bot(
            name="Docs bot",
            widget_key=f"wk_{uuid.uuid4().hex}",
            allowed_origins=["https://example.com"],
            llm_config={"provider": "openai_compatible"},
            embedding_config={"provider": "openai_compatible"},
            system_prompt="Answer only from context.",
            theme={"color": "#0055ff"},
            retrieval_config={"top_k": 5},
        )
        session.add(bot)
        await session.commit()

        found = (await session.execute(select(Bot).where(Bot.name == "Docs bot"))).scalar_one()
        assert found.allowed_origins == ["https://example.com"]
        assert found.retrieval_config["top_k"] == 5
        assert found.id is not None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd server && uv run pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'graft.models'`.

- [ ] **Step 3: Implement `models/base.py`**

```python
import uuid
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class UUIDMixin:
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
```

- [ ] **Step 4: Implement `models/user.py`**

```python
from fastapi_users.db import SQLAlchemyBaseUserTableUUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class User(SQLAlchemyBaseUserTableUUID, TimestampMixin, Base):
    role: Mapped[str] = mapped_column(default="viewer")
```

> `SQLAlchemyBaseUserTableUUID` provides `id` (UUID), `email`, `hashed_password`, `is_active`, `is_superuser`, `is_verified`. Do not add `UUIDMixin` here — the base already defines `id`.

- [ ] **Step 5: Implement `models/bot.py`**

```python
import uuid

from sqlalchemy import ARRAY, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, UUIDMixin


class Bot(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "bots"

    name: Mapped[str] = mapped_column(String(255))
    widget_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    allowed_origins: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    llm_config: Mapped[dict] = mapped_column(JSONB, default=dict)
    embedding_config: Mapped[dict] = mapped_column(JSONB, default=dict)
    system_prompt: Mapped[str] = mapped_column(Text, default="")
    theme: Mapped[dict] = mapped_column(JSONB, default=dict)
    retrieval_config: Mapped[dict] = mapped_column(JSONB, default=dict)


class BotMember(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "bot_members"
    __table_args__ = (UniqueConstraint("user_id", "bot_id", name="uq_bot_member"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"))
    bot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"))
```

> The fastapi-users default table name is `user` (singular) — that is why the FK targets `user.id`.

- [ ] **Step 6: Implement `models/document.py`**

```python
import uuid

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, UUIDMixin


class Document(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "documents"

    bot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(512))
    mime_type: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), default="pending")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
```

- [ ] **Step 7: Implement `models/conversation.py`**

```python
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, UUIDMixin


class Conversation(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "conversations"

    bot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"), index=True)
    visitor_session: Mapped[str] = mapped_column(String(128), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Message(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "messages"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    citations: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
```

- [ ] **Step 8: Implement `models/__init__.py`**

```python
from .base import Base
from .bot import Bot, BotMember
from .conversation import Conversation, Message
from .document import Document
from .user import User

__all__ = ["Base", "User", "Bot", "BotMember", "Document", "Conversation", "Message"]
```

- [ ] **Step 9: Run the test to verify it passes**

Run: `cd server && uv run pytest tests/test_models.py -v`
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add server/graft/models/ server/tests/test_models.py
git commit -m "feat(server): core SQLAlchemy models"
```

---

### Task 5: Alembic + initial migration

**Files:**
- Create: `server/alembic.ini`
- Create: `server/migrations/env.py`
- Create: `server/migrations/script.py.mako`
- Create: `server/migrations/versions/0001_initial.py`
- Modify: `server/tests/conftest.py`
- Test: `server/tests/test_migrations.py`

**Interfaces:**
- Consumes: `graft.models.Base.metadata`, `graft.config.get_settings`.
- Produces: `alembic upgrade head` creates the pgvector extension and all six core tables. conftest gains an autouse `migrated` fixture that runs `alembic upgrade head` against the container **once per session** (replacing ad-hoc `create_all`).

- [ ] **Step 1: Write `server/alembic.ini`**

```ini
[alembic]
script_location = migrations
sqlalchemy.url = postgresql+psycopg://graft:graft@localhost:5432/graft

[loggers]
keys = root

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console

[handler_console]
class = StreamHandler
args = (sys.stderr,)
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
```

- [ ] **Step 2: Write `server/migrations/script.py.mako`**

```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
"""
from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

- [ ] **Step 3: Write `server/migrations/env.py`** (sync, uses `DATABASE_URL` with the psycopg driver)

```python
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from graft.config import get_settings
from graft.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Runtime uses asyncpg; Alembic uses the sync psycopg driver on the same DB.
url = get_settings().database_url.replace("+asyncpg", "+psycopg")
config.set_main_option("sqlalchemy.url", url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **Step 4: Write the failing test** — `server/tests/test_migrations.py`

```python
from sqlalchemy import inspect


async def test_core_tables_exist(db_engine):
    async with db_engine.connect() as conn:
        tables = await conn.run_sync(lambda c: inspect(c).get_table_names())
    for name in ["user", "bots", "bot_members", "documents", "conversations", "messages"]:
        assert name in tables
```

- [ ] **Step 5: Run the test to verify it fails**

Run: `cd server && uv run pytest tests/test_migrations.py -v`
Expected: FAIL — tables missing (no migration has run; the `migrated` fixture does not exist yet).

- [ ] **Step 6: Write the initial migration** — `server/migrations/versions/0001_initial.py`

```python
"""initial schema

Revision ID: 0001
Revises:
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "user",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True, index=True),
        sa.Column("hashed_password", sa.String(1024), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("is_superuser", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("is_verified", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("role", sa.String(32), nullable=False, server_default="viewer"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "bots",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("widget_key", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("allowed_origins", ARRAY(sa.String), nullable=False, server_default="{}"),
        sa.Column("llm_config", JSONB, nullable=False, server_default="{}"),
        sa.Column("embedding_config", JSONB, nullable=False, server_default="{}"),
        sa.Column("system_prompt", sa.Text, nullable=False, server_default=""),
        sa.Column("theme", JSONB, nullable=False, server_default="{}"),
        sa.Column("retrieval_config", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "bot_members",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True),
                  sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("bot_id", UUID(as_uuid=True),
                  sa.ForeignKey("bots.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "bot_id", name="uq_bot_member"),
    )

    op.create_table(
        "documents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("bot_id", UUID(as_uuid=True),
                  sa.ForeignKey("bots.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("filename", sa.String(512), nullable=False),
        sa.Column("mime_type", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("chunk_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "conversations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("bot_id", UUID(as_uuid=True),
                  sa.ForeignKey("bots.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("visitor_session", sa.String(128), nullable=False, index=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "messages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("conversation_id", UUID(as_uuid=True),
                  sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("citations", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    for table in ["messages", "conversations", "documents", "bot_members", "bots", "user"]:
        op.drop_table(table)
```

- [ ] **Step 7: Replace the ad-hoc schema setup in `conftest.py`** with a session-scoped migration fixture

Add to `conftest.py`:

```python
from alembic import command
from alembic.config import Config


@pytest.fixture(scope="session", autouse=True)
def migrated(pg):
    os.environ["DATABASE_URL"] = pg.async_url
    from graft.config import get_settings
    get_settings.cache_clear()
    cfg = Config("alembic.ini")
    cfg.set_main_option("script_location", "migrations")
    cfg.set_main_option("sqlalchemy.url", pg.sync_url)
    command.upgrade(cfg, "head")
    yield
```

Then delete the `CREATE EXTENSION` + `create_all` block from `test_models.py` Step 1 (schema now comes from migrations); the rest of that test is unchanged and still valid.

- [ ] **Step 8: Run the full test suite to verify it passes**

Run: `cd server && uv run pytest -v`
Expected: PASS — `test_health`, `test_db`, `test_models`, `test_migrations` all green.

- [ ] **Step 9: Commit**

```bash
git add server/alembic.ini server/migrations/ server/tests/
git commit -m "feat(server): alembic setup + initial core schema migration"
```

---

### Task 6: Provider-key encryption utility

**Files:**
- Create: `server/graft/security/__init__.py`
- Create: `server/graft/security/crypto.py`
- Test: `server/tests/test_crypto.py`

**Interfaces:**
- Consumes: `graft.config.get_settings().encryption_key` (a Fernet key).
- Produces:
  - `graft.security.crypto.encrypt(plaintext: str) -> str`
  - `graft.security.crypto.decrypt(token: str) -> str`
  - Later phases store provider API keys as `encrypt(key)` and read them via `decrypt(...)`.

- [ ] **Step 1: Write the failing test** — `server/tests/test_crypto.py`

```python
import os

from cryptography.fernet import Fernet


def test_encrypt_decrypt_roundtrip():
    os.environ["ENCRYPTION_KEY"] = Fernet.generate_key().decode()
    from graft.config import get_settings
    get_settings.cache_clear()

    from graft.security import crypto

    secret = "sk-super-secret-provider-key"
    token = crypto.encrypt(secret)
    assert token != secret
    assert crypto.decrypt(token) == secret
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd server && uv run pytest tests/test_crypto.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'graft.security'`.

- [ ] **Step 3: Implement `graft/security/crypto.py`** (and empty `graft/security/__init__.py`)

```python
from cryptography.fernet import Fernet

from ..config import get_settings


def _fernet() -> Fernet:
    return Fernet(get_settings().encryption_key.encode())


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd server && uv run pytest tests/test_crypto.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add server/graft/security/ server/tests/test_crypto.py
git commit -m "feat(server): Fernet encryption for provider secrets"
```

---

### Task 7: `/health/ready` with DB ping

**Files:**
- Modify: `server/graft/api/health.py`
- Modify: `server/tests/conftest.py`
- Test: `server/tests/test_health.py` (add a case)

**Interfaces:**
- Consumes: `graft.db.get_session`.
- Produces: `GET /health/ready` → `200 {"status": "ready"}` when the DB answers `SELECT 1`. Test wires `app.dependency_overrides[get_session]` to the container session.

- [ ] **Step 1: Write the failing test** — add to `server/tests/test_health.py`

```python
async def test_health_ready(ready_client):
    resp = await ready_client.get("/health/ready")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ready"}
```

- [ ] **Step 2: Add the `ready_client` fixture to `conftest.py`** (overrides the DB dependency with the test container)

```python
from graft.db import get_session
from graft.main import app as _app


@pytest_asyncio.fixture
async def ready_client(db_engine):
    maker = async_sessionmaker(db_engine, expire_on_commit=False)

    async def _override():
        async with maker() as session:
            yield session

    _app.dependency_overrides[get_session] = _override
    transport = ASGITransport(app=_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    _app.dependency_overrides.clear()
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd server && uv run pytest tests/test_health.py::test_health_ready -v`
Expected: FAIL — 404 (route `/health/ready` not defined).

- [ ] **Step 4: Add the route to `api/health.py`**

```python
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
async def ready(session: AsyncSession = Depends(get_session)) -> dict[str, str]:
    await session.execute(text("SELECT 1"))
    return {"status": "ready"}
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd server && uv run pytest tests/test_health.py -v`
Expected: PASS (both `test_health_ok` and `test_health_ready`).

- [ ] **Step 6: Run the full suite**

Run: `cd server && uv run pytest -v`
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add server/graft/api/health.py server/tests/
git commit -m "feat(server): /health/ready DB readiness probe"
```

---

## Phase 1 Definition of Done

- `cd server && uv run pytest -v` → all tests green (health, db, models, migrations, crypto, readiness).
- `docker compose config -q` → valid.
- `docker compose up` → `curl localhost:8000/health` returns `{"status":"ok"}`; migrations applied on boot.
- Core schema (`user`, `bots`, `bot_members`, `documents`, `conversations`, `messages`) + pgvector extension present.
- Provider-key encryption available via `graft.security.crypto`.

## What Phase 1 deliberately excludes (later phases)

- `chunks` table + vector storage strategy (Phase 3, spec §6.1).
- Provider adapters (Phase 2), ingestion (Phase 3), RAG + Chat API (Phase 4).
- FastAPI Users auth routers, JWT, RBAC enforcement (Phase 5).
- Admin REST API (Phase 6), Admin SPA (Phase 7), widget (Phase 8).
