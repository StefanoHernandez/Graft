---
title: Architecture
updated: 2026-09-10
sources: [server/graft/main.py, server/graft/api/*.py, server/graft/security/auth.py, server/graft/cli.py, server/graft/config.py, server/graft/db.py, server/graft/api/health.py, docker-compose.yml, server/Dockerfile, server/entrypoint.sh, docs/superpowers/specs/2026-09-08-graft-design.md]
source_commit: 2b9c4cb
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

`[P#]` = planned in that phase; ✅ = implemented. The redesign plan renumbers these
as tasks — see [roadmap](../project/roadmap.md).

## What runs today

- **App factory** — `graft.main.create_app()` builds the FastAPI app, adds CORS
  middleware (`allow_origins = settings.cors_origins or ["*"]` for now; per-bot
  origin enforcement arrives with the Chat API), and includes the health router, the
  **login router only** (`/auth/jwt/login`), and the admin router.
  Module-level `app = create_app()` is the ASGI entrypoint (`graft.main:app`).
- **Config** — `graft.config.Settings` (pydantic-settings), read once via
  `get_settings()` (`lru_cache`). Fields: `database_url`, `redis_url`, `jwt_secret`,
  `encryption_key`, `cors_origins`, `app_env`, `storage_root`. Loaded from env / `.env`.
  With `APP_ENV=prod` a placeholder JWT secret or an invalid Fernet key fails startup.
- **Database** — `graft.db`: `get_engine()` / `get_sessionmaker()` (both cached) build
  an async SQLAlchemy engine (`asyncpg`) from `settings.database_url`; `get_session()`
  is the FastAPI dependency yielding an `AsyncSession`.
- **Health** — `GET /health` → `{"status":"ok"}`; `GET /health/ready` runs
  `SELECT 1` through `get_session` and returns `{"status":"ready"}` (readiness probe).
- **Security** — `graft.security.crypto.encrypt/decrypt` (Fernet, keyed by
  `settings.encryption_key`) protect provider API keys at rest.
  `graft.security.auth` wires FastAPI Users: JWT bearer, 1-hour tokens, and
  `current_owner`, which every admin route depends on. **There is no registration
  router**: accounts come from `python -m graft.cli create-admin EMAIL`, which asks for
  the password without echo and takes a transaction-scoped advisory lock so two
  concurrent bootstraps cannot both create an owner. Editor and viewer exist in the
  schema but are refused by the admin API until RBAC is actually enforced — granting
  them access earlier would ship an unenforced permission.
- **Admin API** — `graft.api.admin`, prefix `/api/v1/admin`, owner-only:
  bots (list/create/patch/delete, `{items, total}` paging capped at 100), provider test
  (a real minimal chat **and** a real minimal embedding — a key can list models it may
  not call), documents (list, multipart upload, retry, delete). Invariants worth
  keeping: an API key is encrypted before it is persisted and responses carry only
  `has_api_key`; in a PATCH an **omitted** key is kept and an **explicit null** clears
  it; an upload takes the bot row lock so it cannot race a change of embedding config;
  changing the embedding config of a bot that already has documents is `409
  embedding_config_locked`, while rotating just the key is allowed; a delete revokes the
  row first and removes the file afterwards, because a stray file is a chore and a stray
  row is a live document.

## Sub-packages

| Package | Responsibility | Page |
|---|---|---|
| `graft.models` | SQLAlchemy models + one shared `Base` | [data-model](data-model.md) |
| `graft.providers` | LLM/embeddings Protocols, adapters, factory | [providers](providers.md) |
| `graft.ingestion` | parse → chunk → embed → store | [ingestion](ingestion.md) |
| `graft.security` | Fernet encryption, JWT auth, owner guard | (this page) |
| `graft.api` | HTTP routers: health, admin | (this page) |
| `graft.cli` | operator commands (`create-admin`) | (this page) |
| `migrations` | Alembic (0001 core, 0002 chunks, 0003 lifecycle) | [data-model](data-model.md) |

## Two DB drivers, one database

- **Runtime** uses async **`asyncpg`** (`postgresql+asyncpg://`).
- **Alembic** migrations run **sync** via **`psycopg`**; `migrations/env.py` uses an
  explicit url when a caller sets one and otherwise falls back to `settings.database_url`,
  replacing `+asyncpg` with `+psycopg`.

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
