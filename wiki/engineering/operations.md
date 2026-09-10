---
title: Operations
updated: 2026-09-10
sources: [docker-compose.yml, server/Dockerfile, server/entrypoint.sh, server/graft/config.py, .env.example]
source_commit: 4826fc6
confidence: high
---

# Operations

## Running the stack

```bash
cp .env.example .env
# set ENCRYPTION_KEY to a Fernet key:
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
docker compose up
```

- `db` — `pgvector/pgvector:pg16`, `pg_isready` healthcheck, named volume `graft_db`
  (data persists across restarts).
- `redis` — `redis:7-alpine` (used from Phase 3b).
- `app` — built from `server/Dockerfile`; waits for db healthy + redis; `entrypoint.sh`
  runs `alembic upgrade head` then `uvicorn graft.main:app --host 0.0.0.0 --port 8000`.

Health checks: `GET /health` (liveness) and `GET /health/ready` (DB probe).

## Configuration

All via env (`.env`, `env_file` in compose). See the table in the root `README.md`.
Critical:

- **`ENCRYPTION_KEY`** — Fernet key; encrypts provider API keys at rest. If unset,
  encryption/decryption fails loudly on first use. Rotating it invalidates previously
  encrypted keys.
- **`DATABASE_URL`** — async (`+asyncpg`) at runtime; Alembic derives the `+psycopg`
  sync URL itself.
- Provider API keys and per-bot config are **not** env vars — they live in the `bots`
  table (set via the Admin API/SPA, Phases 6/7), with keys encrypted.

## Migrations in production

The entrypoint runs `alembic upgrade head` on every boot and **fails the container** on a
real migration error (it no longer masks failures). The `db` healthcheck gates startup so
the app does not race an unready database.

## Known operational gaps (by phase)

- **No public Chat API / widget yet** — nothing serves end-user traffic before Phase 4/8.
- **Ingestion is synchronous** — the Redis worker is Phase 3b; large PDFs currently have
  no size/time guard (add at the Phase 6 upload boundary).
- **Rate limiting** (Redis) and **per-bot CORS origin enforcement** arrive with the Chat
  API (Phase 4); today CORS defaults to `*`.
- **Provider endpoints:** Google/Mistral go through their OpenAI-compatible endpoints.
  Before declaring them production-ready, run a one-off live smoke test (a streaming chat
  and a batch embed) against each — unit tests use fakes and cannot catch a live-endpoint
  quirk (Gemini's compat layer is beta).

## Backups

Back up the `graft_db` Postgres volume (chunks + config + conversations). Uploaded raw
files are not stored yet (only parsed chunks); the source-file storage decision belongs to
the Phase 6 upload endpoint.
