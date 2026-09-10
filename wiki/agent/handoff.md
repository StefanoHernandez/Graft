---
title: Handoff — start here
updated: 2026-09-10
sources: [README.md, docs/superpowers/**, docs/superpowers/specs/2026-09-10-graft-redesign.md, docs/superpowers/plans/2026-09-10-graft-redesign-plan.md]
source_commit: c16dbae
confidence: high
---

# Handoff — start here

## Baton For Next Coding Agent

Read [the revised spec](../../docs/superpowers/specs/2026-09-10-graft-redesign.md) and [the detailed plan](../../docs/superpowers/plans/2026-09-10-graft-redesign-plan.md). Future-work instructions below this section are historical and superseded where they conflict. No application code was changed in this planning pass.

| Order | Task | Start files | Done when | Verification command | Notes / blockers |
|---|---|---|---|---|---|
| 1 | Plan task 0: baseline and test separation | server/tests/conftest.py; new plan | Unit tests run without Docker; integration still uses migrations | From server: `uv run pytest tests/unit -q` after task 0 | Not verified; virtualenv absent during planning |
| 2 | Plan tasks 1–6: reliable ingestion | new spec sections 4–6 | Gate A: authenticated upload survives worker restart | From server after implementation: `uv run pytest tests/integration -q` | Includes auth and source storage |
| 3 | Plan tasks 7–11: RAG and widget | new plan | Gate B: widget demo and live evidence | Plan tasks 10–11 commands | Live credentials required |
| 4 | Plan tasks 12–14: release | new plan | Gate C: admin, build and restore verified | Plan tasks 12–14 commands | Licence selection before public release |

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
