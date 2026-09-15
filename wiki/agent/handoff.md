---
title: Handoff — start here
updated: 2026-09-15
sources: [README.md, docs/superpowers/**, docs/superpowers/specs/2026-09-10-graft-redesign.md, docs/superpowers/plans/2026-09-10-graft-redesign-plan.md]
source_commit: 5239138
confidence: high
---

# Handoff — start here

## Baton For Next Coding Agent

Tasks 0–14 of [the plan](../../docs/superpowers/plans/2026-09-10-graft-redesign-plan.md)
are done and on `feat/graft-redesign-a`. Graft works end to end: upload a document through
`/admin/`, a worker ingests it, and the widget answers on another origin with a checkable
source. Evidence for each gate is in [status](../project/status.md).

Run it yourself before changing anything:

```bash
cp .env.example .env      # put a real Fernet key in ENCRYPTION_KEY
docker compose up -d
docker compose exec app /app/.venv/bin/python -m graft.cli create-admin you@example.com
open http://localhost:8000/admin/
```

| Order | Task | Start here | Done when |
|---|---|---|---|
| 1 | Choose a licence | root `README.md` | The owner decides; do not pick one for them |
| 2 | Verify the other five providers | `docs/evidence/rag-baseline.md`, `server/tests/live/` | Each backend has a dated live result; today only Mistral does |
| 3 | Plan task 15: RBAC | `server/graft/security/auth.py` | Editor and viewer enforced on the backend before any button is hidden |
| 4 | Plan task 16: Refine dashboard | `server/graft/static/admin/` | Parity with the current surface before it is removed |

House rules that are not obvious from the code:

- **Test-first**, `uv run ruff check .` clean, and **zero warnings** in the test output.
- The unit tier must keep running with Docker down: `DOCKER_HOST=unix:///nonexistent uv run pytest tests/unit -q`.
- Migrations match the models exactly — CI runs `alembic check`.
- Provider keys are never logged, never returned by the API, and never put in a job payload.
- UI work follows [DESIGN.md](../../DESIGN.md) and [PRODUCT.md](../../PRODUCT.md); the
  direction contract for the admin surface lives in `.impeccable/surfaces/`.

Welcome. This is the fastest path to being productive on Graft.

## 1. Understand what it is (15 min)

- Read the root [README](../../README.md) and [overview](../overview.md).
- Skim the design spec: `docs/superpowers/specs/2026-09-08-graft-design.md` (the source of truth).

## 2. Get it running (10 min)

```bash
cd server
uv run pytest -v          # green + 0 warnings confirms your toolchain (needs Docker running)
```

Optional full stack:

```bash
cp ../.env.example ../.env
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # -> ENCRYPTION_KEY in ../.env
docker compose up          # from repo root; app on :8000
```

## 3. Learn the shape (30 min)

- [architecture](../engineering/architecture.md) — how the pieces fit.
- [data-model](../engineering/data-model.md) — tables, the dimensionless-vector decision.
- [providers](../engineering/providers.md) and [ingestion](../engineering/ingestion.md) — the two
  built subsystems.
- [change-map](../engineering/change-map.md) — "to change X, start here".

## 4. Do the next unit of work

The project advances **phase by phase**; the next is **Phase 3b (Redis ingestion worker)**.

1. Look at how prior phases are specified: `docs/superpowers/plans/*.md` (bite-sized TDD,
   file-by-file, with exact code). This is the house style — write the Phase 3b plan the same way.
2. Phase 3b outline (from [roadmap](../project/roadmap.md) / [change-map](../engineering/change-map.md)):
   add a Redis queue (`graft/ingestion/queue.py`) + a worker entrypoint that, per enqueued
   document, builds the embedder via `providers.factory.build_embedder(EmbeddingConfig(**bot.embedding_config))`
   and calls `ingestion.pipeline.ingest_document`. Redis is already in `docker-compose.yml`.
3. Honor the conventions in [development](../engineering/development.md): TDD, ruff clean,
   pristine tests, migrations match models, no logged secrets.

## 5. Working conventions

- Branch off `main`; Conventional Commits; open a PR (or merge locally per the owner's flow).
- Every change ships with tests; keep the suite green and warning-free.
- Update the relevant `wiki/engineering/*` page + `wiki/log.md` when you change behavior.

## Things not to trip on

See the "Gotchas" in [agent/context](context.md): dimensionless vectors need per-bot
retrieval; Alembic uses sync psycopg; chunk metadata attr is `chunk_metadata`; normalize
provider stream errors before the Phase 4 SSE endpoint; Google/Mistral run on OpenAI-compat
endpoints.
