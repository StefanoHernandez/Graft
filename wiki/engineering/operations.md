---
title: Operations
updated: 2026-09-10
sources: [docker-compose.yml, server/Dockerfile, server/entrypoint.sh, server/graft/config.py, .env.example]
source_commit: 408c597
confidence: high
---

# Operations

## Running the stack

```bash
cp .env.example .env
# set ENCRYPTION_KEY to a Fernet key:
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
docker compose up -d

# create the operator account (asks for the password, no echo)
docker compose exec app /app/.venv/bin/python -m graft.cli create-admin you@example.com
```

Local work adds the dev override, which is the only place Postgres and Redis are
published: `docker compose -f docker-compose.yml -f docker-compose.dev.yml up`. The base
file deliberately publishes **only** the app, because a database reachable from the
internet is a database that will be found.

Full operating guide — upgrades, backup, a verified restore, retention and the legacy
report — is [docs/operations/first-release.md](../../docs/operations/first-release.md).

- `db` — `pgvector/pgvector:pg16`, `pg_isready` healthcheck, named volume `graft_db`
  (data persists across restarts).
- `redis` — `redis:7-alpine` with `--appendonly yes` and the `graft_redis` volume, so a
  restart does not silently drop queued jobs.
- `app` — built from `server/Dockerfile` with the **repo root** as context, so the image
  also carries the widget bundle built by a pinned Node stage. `uv` and Node are pinned by
  **digest**, and `uv sync --frozen` installs what the lockfile resolved or fails: a build
  that quietly picks newer versions is not the build that was tested. The entrypoint calls
  the venv binaries directly, so nothing resolves, syncs or reaches the network at boot.
  It runs `alembic upgrade head` then `uvicorn graft.main:app`.
- `worker` — the **same image**, entrypoint replaced by
  `uv run arq graft.ingestion.worker.WorkerSettings`. It waits for the app to be healthy
  and deliberately does **not** run Alembic: migrations happen once, from the app, or the
  two race on every deploy. Upgrades: stop the worker, migrate, start it again.
- `graft_uploads` is mounted by both app and worker — the worker re-reads the original on
  every attempt, so they must see the same volume.

Health checks: `GET /health` is liveness and touches nothing, so it answers even when
every dependency is down. `GET /health/ready` checks the **database, Redis and the uploads
volume** and returns 503 naming the one that failed; it is what the worker's `depends_on`
waits for, so a worker never starts against a half-configured host.

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

## Operator commands

All three report by default and act only with `--apply`:

- `legacy-report` — documents with no stored original, or **ready** documents with no
  embedding fingerprint (their chunks exist but retrieval skips them). A *failed*
  document without a fingerprint is not listed: it never finished, which is a different
  problem.
- `cleanup-conversations --days 30 [--apply]` — retention; messages follow by cascade.
- `cleanup-orphan-files [--apply]` — stored originals with no document row, which appear
  when a delete removed the row and the file cleanup failed after it.

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
