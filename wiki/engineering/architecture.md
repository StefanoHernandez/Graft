---
title: Architecture
updated: 2026-09-10
sources: [server/graft/main.py, server/graft/config.py, server/graft/db.py, server/graft/api/health.py, docker-compose.yml, server/Dockerfile, server/entrypoint.sh, docs/superpowers/specs/2026-09-08-graft-design.md]
source_commit: 4826fc6
confidence: high
---

# Architecture

Graft is a **modular monolith**: one FastAPI service (`graft`) will host the public
Chat API, the Admin API + SPA, the ingestion pipeline, the RAG engine, and the
provider adapters. Microservices were deliberately rejected as overkill for a
self-hosted MVP (spec §3).

## Runtime shape (target)

```
Host page  ──<script>──►  graft.js (Shadow DOM)        [Phase 8 — not built]
                                │ HTTP/SSE (CORS: per-bot allowed_origins)
                                ▼
                    ┌───────────────────────────────┐
                    │  graft-server (FastAPI)         │
                    │  • Chat API (public, SSE)  [P4] │
                    │  • Admin API + SPA        [P6/7]│
                    │  • Ingestion pipeline  ✅        │
                    │  • RAG engine             [P4]  │
                    │  • Provider adapters  ✅          │
                    └───────────────┬───────────────┘
                                    ▼
                    Postgres + pgvector ✅     Redis (queue/rate-limit) [P3b]
```

`[P#]` = planned in that phase; ✅ = implemented at commit 4826fc6.

## What runs today

- **App factory** — `graft.main.create_app()` builds the FastAPI app, adds CORS
  middleware (`allow_origins = settings.cors_origins or ["*"]` for now; per-bot
  origin enforcement arrives with the Chat API), and includes the health router.
  Module-level `app = create_app()` is the ASGI entrypoint (`graft.main:app`).
- **Config** — `graft.config.Settings` (pydantic-settings), read once via
  `get_settings()` (`lru_cache`). Fields: `database_url`, `redis_url`, `jwt_secret`,
  `encryption_key`, `cors_origins`, `app_env`. Loaded from env / `.env`.
- **Database** — `graft.db`: `get_engine()` / `get_sessionmaker()` (both cached) build
  an async SQLAlchemy engine (`asyncpg`) from `settings.database_url`; `get_session()`
  is the FastAPI dependency yielding an `AsyncSession`.
- **Health** — `GET /health` → `{"status":"ok"}`; `GET /health/ready` runs
  `SELECT 1` through `get_session` and returns `{"status":"ready"}` (readiness probe).
- **Security** — `graft.security.crypto.encrypt/decrypt` (Fernet, keyed by
  `settings.encryption_key`) protect provider API keys at rest.

## Sub-packages

| Package | Responsibility | Page |
|---|---|---|
| `graft.models` | SQLAlchemy models + one shared `Base` | [data-model](data-model.md) |
| `graft.providers` | LLM/embeddings Protocols, adapters, factory | [providers](providers.md) |
| `graft.ingestion` | parse → chunk → embed → store | [ingestion](ingestion.md) |
| `graft.security` | Fernet encryption for secrets | (this page) |
| `graft.api` | HTTP routers (only health today) | (this page) |
| `migrations` | Alembic (0001 core schema, 0002 chunks) | [data-model](data-model.md) |

## Two DB drivers, one database

- **Runtime** uses async **`asyncpg`** (`postgresql+asyncpg://`).
- **Alembic** migrations run **sync** via **`psycopg`**; `migrations/env.py` derives the
  sync URL by replacing `+asyncpg` with `+psycopg` on `settings.database_url`.

## Deployment

`docker-compose.yml` defines three services:

- `db` — `pgvector/pgvector:pg16` with a `pg_isready` healthcheck + named volume `graft_db`.
- `redis` — `redis:7-alpine` (used from Phase 3b).
- `app` — built from `server/Dockerfile`; `depends_on` db (healthy) + redis; `env_file: .env`;
  port 8000. `entrypoint.sh` runs `alembic upgrade head` (fails the boot on a real
  migration error) then `exec uvicorn graft.main:app`.

The base image is Python 3.12-slim; `server/.dockerignore` keeps the local venv,
caches, and tests out of the build context. `pypdf` is the only extra parsing dep in
the base image (`unstructured` is a deferred optional backend).

## Design invariants

- One shared `Base` (`graft.models.base.Base`) so Alembic sees one metadata and
  FastAPI Users (Phase 5) can extend it.
- Migrations must match the ORM models **exactly** (types, nullability, FKs).
- Provider secrets are never stored or logged in plaintext.
- The vector column is dimensionless; retrieval is always per-bot (see
  [data-model](data-model.md) and [decisions](../project/decisions.md)).
