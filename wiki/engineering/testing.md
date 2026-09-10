---
title: Testing
updated: 2026-09-10
sources: [server/tests/*.py, server/pyproject.toml]
source_commit: 4826fc6
confidence: high
---

# Testing

- **Runner:** `pytest` with `pytest-asyncio` in **auto** mode
  (`asyncio_mode = "auto"`, `asyncio_default_fixture_loop_scope = "function"`), from `server/`.
- **Real Postgres:** `server/tests/conftest.py` starts one ephemeral
  `pgvector/pgvector:pg16` container per session via **testcontainers**
  (`testcontainers.community.postgres.PostgresContainer`), exposing `.sync_url`
  (psycopg) and `.async_url` (asyncpg).
- **Schema via migrations:** a session-scoped autouse `migrated` fixture points
  `DATABASE_URL` at the container and runs `alembic upgrade head`, so tests exercise the
  real migrated schema (not `create_all`).
- **Fixtures:** `db_engine` (async engine), `db_session` (async session), `client`
  (httpx `AsyncClient` over the ASGI app), `ready_client` (overrides `get_session` with a
  container session for the readiness probe).
- **No network:** provider and ingestion tests inject **fakes** (`types.SimpleNamespace` /
  small fake classes), so they never call a real API.
- **Pristine output required:** the suite must pass with **0 warnings**.

## Suite (13 files, 46 tests at commit 4826fc6)

| File | Covers |
|---|---|
| `test_health.py` | `/health`, `/health/ready` |
| `test_db.py` | async engine/session against the container |
| `test_models.py` | core models round-trip (ARRAY/JSONB) |
| `test_migrations.py` | `alembic upgrade head` creates the core tables |
| `test_crypto.py` | Fernet encrypt/decrypt round-trip |
| `test_chunks_model.py` | `chunks` table round-trip (dimensionless vector) |
| `test_providers_base.py` | Protocols, config defaults, error hierarchy |
| `test_providers_openai.py` | streaming deltas, embed order, error wrapping |
| `test_providers_anthropic.py` | system extraction, max_tokens default, temperature via extra_body |
| `test_providers_factory.py` | branch dispatch, default base_urls, decrypt-failure → ProviderError |
| `test_ingestion_parsing.py` | pdf (monkeypatched)/md/txt/unsupported |
| `test_ingestion_chunking.py` | overlap, empty, param validation |
| `test_ingestion_pipeline.py` | store chunks, empty re-ingest clears, failure → failed |

## Running

```bash
cd server
uv run pytest -v            # all
uv run pytest -q            # quiet
uv run pytest tests/test_ingestion_pipeline.py -v
```

If a run errors before any test, check that **Docker is running** (testcontainers needs it).
