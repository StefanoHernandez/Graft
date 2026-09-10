---
title: Handoff — start here
updated: 2026-09-10
sources: [README.md, docs/superpowers/**]
source_commit: 4826fc6
confidence: high
---

# Handoff — start here

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
