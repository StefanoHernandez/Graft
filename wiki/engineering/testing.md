---
title: Testing
updated: 2026-09-10
sources: [server/tests/**/*.py, server/pyproject.toml]
source_commit: a7dce77
confidence: high
---

# Testing

- **Runner:** `pytest` with `pytest-asyncio` in **auto** mode
  (`asyncio_mode = "auto"`, `asyncio_default_fixture_loop_scope = "function"`), from `server/`.
- **Two tiers:** `tests/unit/` runs with **no Docker and no network** (~1s);
  `tests/integration/` needs a real Postgres. The root `tests/conftest.py` holds only the
  DB-free `client` fixture; every container fixture lives in `tests/integration/conftest.py`,
  so an absent Docker daemon cannot break the unit tier.
- **Markers:** `integration` is applied automatically to everything under
  `tests/integration/`; `live` marks opt-in tests that call a real provider and is
  **excluded by default** (`addopts = "-m 'not live'"`).
- **Real Postgres:** `tests/integration/conftest.py` starts one ephemeral
  `pgvector/pgvector:pg16` container per session via **testcontainers**
  (`testcontainers.community.postgres.PostgresContainer`), exposing `.sync_url`
  (psycopg) and `.async_url` (asyncpg).
- **Schema via migrations:** a session-scoped autouse `migrated` fixture points
  `DATABASE_URL` at the container and runs `alembic upgrade head`, so tests exercise the
  real migrated schema (not `create_all`).
- **Fixtures:** `client` (httpx `AsyncClient` over the ASGI app, root conftest, no DB);
  integration-only: `db_engine` (async engine), `db_session` (async session),
  `ready_client` (overrides `get_session` with a container session for the readiness probe).
- **No network:** provider and ingestion tests inject **fakes** (`types.SimpleNamespace` /
  small fake classes), so they never call a real API.
- **Pristine output required:** the suite must pass with **0 warnings**.

## Suite (14 files, 46 tests at commit a7dce77 — 37 unit + 9 integration)

### Unit — `tests/unit/`, no Docker (37)

| File | Covers |
|---|---|
| `test_health.py` | `/health` liveness |
| `test_crypto.py` | Fernet encrypt/decrypt round-trip |
| `test_providers_base.py` | Protocols, config defaults, error hierarchy |
| `test_providers_openai.py` | streaming deltas, embed order, error wrapping |
| `test_providers_anthropic.py` | system extraction, max_tokens default, temperature via extra_body |
| `test_providers_factory.py` | branch dispatch, default base_urls, decrypt-failure → ProviderError |
| `test_ingestion_parsing.py` | pdf (monkeypatched)/md/txt/unsupported |
| `test_ingestion_chunking.py` | overlap, empty, param validation |

### Integration — `tests/integration/`, Docker required (9)

| File | Covers |
|---|---|
| `test_health.py` | `/health/ready` readiness against the container |
| `test_db.py` | async engine/session against the container |
| `test_models.py` | core models round-trip (ARRAY/JSONB) |
| `test_migrations.py` | `alembic upgrade head` creates the core tables |
| `test_chunks_model.py` | `chunks` table round-trip (dimensionless vector) |
| `test_ingestion_pipeline.py` | store chunks, empty re-ingest clears, failure → failed |

## Running

```bash
cd server
uv run pytest -q                  # all 46 (Docker required)
uv run pytest tests/unit -q       # 37, no Docker, ~1s
uv run pytest -m integration -q   # 9, Docker required
uv run pytest -m live -q          # opt-in provider tests (none yet)
```

Only the integration tier needs Docker; if it errors before any test, check that the
daemon is running (testcontainers needs it). Unit tests must keep passing with the
daemon down — verify with
`DOCKER_HOST=unix:///nonexistent-graft.sock uv run pytest tests/unit -q`.
