---
title: Agent context
updated: 2026-09-15
sources: [docs/superpowers/**, server/graft/**, docs/superpowers/specs/2026-09-10-graft-redesign.md, docs/superpowers/plans/2026-09-10-graft-redesign-plan.md]
source_commit: 5239138
confidence: high
---

# Agent context

## Read first — 2026-09-11

Tasks 0–14 of the [execution plan](../../docs/superpowers/plans/2026-09-10-graft-redesign-plan.md)
are implemented; the [revised spec](../../docs/superpowers/specs/2026-09-10-graft-redesign.md)
is the scope of record and the phase queue further down this page is history.

Decisions that constrain new work, each of them load-bearing:

- **Retrieval filters on the embedding fingerprint, never on dimension.** Two vectors of
  the same length from different models are not comparable.
- **The run id in the database is the fencing token**, not the queue. arq is at-least-once,
  so a duplicated job, a resumed worker or a stale attempt must not publish over fresher work.
- **Nothing is answered without a retrieved chunk.** No context means a fixed refusal and
  no model call, and a citation pointing at a chunk nobody retrieved is discarded.
- **The admin token lives in memory only.** The visitor's session id is not a secret the
  server keeps: it is minted server-side (256 random bits), returned to the widget in the
  `meta` event and sent back on every turn. Whoever holds it can continue that
  conversation, which is why it is random rather than guessable; the admin surface shows
  only an 8-character label.
- **One owner** in this release. Editor and viewer exist in the schema and are refused by
  the API, because shipping an unenforced permission is worse than not having one.

Durable context for whoever (human or AI) works on Graft next.

## What Graft is

A self-hosted OSS framework to add a RAG chatbot to any existing website via one
`<script>` tag (Shadow-DOM widget), zero host-backend changes. Self-hosted `graft-server`
(FastAPI + Postgres/pgvector + Redis), bring-your-own-model, multi-bot, strict-grounded.

## How the project is run

- **Source of truth:** the design spec `docs/superpowers/specs/2026-09-08-graft-design.md`.
- **Work unit:** a **phase** with a bite-sized **TDD plan** in `docs/superpowers/plans/`.
  Implement test-first → review → merge to `main` when green.
- **Non-negotiables:** ruff clean; pytest pristine (0 warnings); migrations match models
  exactly; secrets encrypted, never logged; DI at seams so tests need no network.

## Ground truth about the current code (commit 4826fc6)

- Backend lives in `server/` (package `graft`); `uv` manages deps; tests use a real
  pgvector container via testcontainers (**Docker must be running**).
- Implemented: app/config/db/health, Fernet crypto, all models + migrations 0001/0002,
  the 6-backend provider layer + factory, the synchronous ingestion pipeline.
- Not implemented: Redis ingestion worker (3b), RAG retrieval + Chat API (4), auth/RBAC
  (5), Admin API (6), Admin SPA (7), widget (8).

## Gotchas to remember

- The `chunks.embedding` column is **dimensionless**; retrieval must always filter by
  `bot_id`. A bot changing embedding model after ingestion makes its chunks mixed-dimension
  and breaks `<=>` — force a re-embed then.
- Alembic uses the **sync** psycopg driver (env.py swaps `+asyncpg`→`+psycopg`).
- The chunk metadata column is SQL `metadata` but Python attribute `chunk_metadata`.
- Provider `stream_chat`/`embed` currently leak native SDK errors — **normalize before the
  SSE Chat endpoint (Phase 4)**.
- Google/Mistral run on their **OpenAI-compatible** endpoints (beta for Gemini) — smoke-test
  live before GA.
- This environment resolves high SDK versions (openai 3.8.0, anthropic 1.4.0); adapters use
  only stable surface and tests use fakes.

## Links

- Start: [handoff](handoff.md) · Build map: [change-map](../engineering/change-map.md)
- Architecture: [architecture](../engineering/architecture.md) · Data: [data-model](../engineering/data-model.md)
- Providers: [providers](../engineering/providers.md) · Ingestion: [ingestion](../engineering/ingestion.md)
- Status: [status](../project/status.md) · Roadmap: [roadmap](../project/roadmap.md) · Decisions: [decisions](../project/decisions.md)
