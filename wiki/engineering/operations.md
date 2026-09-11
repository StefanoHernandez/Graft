---
title: Operations
updated: 2026-09-10
sources: [docker-compose.yml, server/Dockerfile, server/entrypoint.sh, server/graft/config.py, .env.example]
source_commit: 9a58098
confidence: high
---

# Operations

## Running the stack

```bash
cp .env.example .env
# set ENCRYPTION_KEY to a Fernet key:
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
docker compose up

# create the operator account (asks for the password, no echo)
docker compose exec app uv run python -m graft.cli create-admin you@example.com
```

- `db` — `pgvector/pgvector:pg16`, `pg_isready` healthcheck, named volume `graft_db`
  (data persists across restarts).
- `redis` — `redis:7-alpine` with `--appendonly yes` and the `graft_redis` volume, so a
  restart does not silently drop queued jobs.
- `app` — built from `server/Dockerfile`; waits for db and redis healthy; `entrypoint.sh`
  runs `alembic upgrade head` then `uvicorn graft.main:app --host 0.0.0.0 --port 8000`.
- `worker` — the **same image**, entrypoint replaced by
  `uv run arq graft.ingestion.worker.WorkerSettings`. It waits for the app to be healthy
  and deliberately does **not** run Alembic: migrations happen once, from the app, or the
  two race on every deploy. Upgrades: stop the worker, migrate, start it again.
- `graft_uploads` is mounted by both app and worker — the worker re-reads the original on
  every attempt, so they must see the same volume.

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
- **Queue semantics are at-least-once.** arq can run a job twice; the run id in the
  database is what decides whose result counts. A crash after the commit but before the
  ack replays the job, which then sees `ready` and exits. Repeated embedding calls after a
  crash can cost money twice — accepted, this is not exactly-once.
- **Losing Redis loses latency, not work.** The dispatcher sweeps Postgres every minute
  for `pending` documents and expired leases and re-enqueues them, and an upload whose
  enqueue fails still commits its row. A document that exhausts its three attempts is
  marked `failed` with `attempts_exhausted` — nothing stays in `processing` forever.
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
