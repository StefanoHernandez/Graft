---
title: Agent context
updated: 2026-09-10
sources: [docs/superpowers/**, server/graft/**, docs/superpowers/specs/2026-09-10-graft-redesign.md, docs/superpowers/plans/2026-09-10-graft-redesign-plan.md]
source_commit: c16dbae
confidence: high
---

# Agent context

## Read first for future work — 2026-09-10

Read the [revised spec](../../docs/superpowers/specs/2026-09-10-graft-redesign.md) and [execution plan](../../docs/superpowers/plans/2026-09-10-graft-redesign-plan.md) before following the older phase queue below. These documents change future scope/order, not current code. First release keeps multi-bot but limits admin to one owner; RBAC and Refine follow later. Original files, provenance and worker recovery precede public chat. No runtime changes or new passing tests are claimed.

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
