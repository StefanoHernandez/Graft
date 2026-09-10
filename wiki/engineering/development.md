---
title: Development
updated: 2026-09-10
sources: [server/pyproject.toml, README.md, docs/superpowers/plans/*, server/tests/conftest.py]
source_commit: 4826fc6
confidence: high
---

# Development

## Prerequisites

- **Python ≥ 3.12**, **[uv](https://docs.astral.sh/uv/)**, **Docker** (running — the
  test suite starts a real Postgres via testcontainers).

## Everyday commands (run from `server/`)

```bash
uv run pytest -v                 # full test suite (spins pgvector container)
uv run pytest tests/test_x.py -v # one file
uv run ruff check .              # lint
uv run ruff check --fix .        # autofix + sort imports
uv run alembic upgrade head      # apply migrations (needs a reachable DB)
uv run alembic revision -m "..." # new migration (author to match models exactly)
```

`uv run` auto-syncs the venv from `pyproject.toml`; no separate install step.

## Conventions (how work lands here)

The project is built **phase by phase**. Each phase has a spec-derived, bite-sized
**TDD plan** in `docs/superpowers/plans/`, is implemented test-first, reviewed, and
merged to `main` only when green. New work should follow the same shape.

- **TDD:** write the failing test, then the minimal code, then commit.
- **Lint clean + pristine tests:** `uv run ruff check .` passes; pytest shows **0 warnings**.
- **Migrations match models exactly** (types, nullability, FKs, indexes). A model/migration
  mismatch is a blocking defect.
- **Secrets:** provider API keys are encrypted (Fernet) and **never logged**; `.env` is
  git-ignored (only `.env.example` is tracked).
- **Dependency injection at seams:** provider adapters and the ingestion pipeline take
  their client/embedder by argument, so tests use fakes (no network).
- **Commit messages:** Conventional Commits (`feat(server): …`, `fix(server): …`,
  `docs: …`, `refactor(server): …`).

## Package layout (`server/graft`)

```
main.py config.py db.py        app factory, settings, async DB
api/health.py                  routers (only health today)
security/crypto.py             Fernet encrypt/decrypt
models/                        SQLAlchemy models + Base/mixins
providers/                     Protocols, adapters, factory
ingestion/                     parse, chunk, store, pipeline
migrations/                    Alembic env + versions
tests/                         pytest (see testing.md)
```

## Adding a dependency

Edit `server/pyproject.toml` (`[project].dependencies` or `[dependency-groups].dev`),
then run any `uv run …` command — it re-resolves and updates `server/uv.lock`. Commit the
lockfile with the change.

## Notes

- This environment resolves unusually high SDK versions (`openai 3.8.0`, `anthropic 1.4.0`,
  `pypdf 6.x`). Pins carry upper bounds where it matters (`openai>=1.40,<4`).
- Local dev may run Python 3.14 while the Docker image pins 3.12; both satisfy `>=3.12`.
