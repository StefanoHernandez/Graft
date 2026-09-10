---
title: Decisions
updated: 2026-09-10
sources: [docs/superpowers/specs/2026-09-08-graft-design.md, server/graft/**, docs/superpowers/specs/2026-09-10-graft-redesign.md, docs/superpowers/plans/2026-09-10-graft-redesign-plan.md]
source_commit: c16dbae
confidence: high
---

# Decisions

## Planned redesign decisions — 2026-09-10

The [new spec](../../docs/superpowers/specs/2026-09-10-graft-redesign.md) selects persistent originals, provenance-aware chunking, embedding fingerprint/config lock, Redis/arq worker with leases, owner auth before upload, widget before full dashboard, and a live RAG evaluation gate. These are implementation targets, not properties of the current code. The existing architecture and completed phases remain. Full multi-user RBAC/Refine is deferred beyond the first release, not removed.

Key choices and why. Each links to the engineering page that implements it.

- **Self-hosted standalone Docker service** (not SaaS, not per-language SDK). The host
  site integrates only via one `<script>` tag; the host backend is never touched.
  → [architecture](../engineering/architecture.md)
- **Python + FastAPI backend.** Richest RAG ecosystem (parsing, embeddings SDKs), async
  streaming for SSE. → [architecture](../engineering/architecture.md)
- **Single Postgres + pgvector** for vectors and relational data — one engine to run/back up.
  → [data-model](../engineering/data-model.md)
- **Dimensionless vector column + exact KNN, per-bot.** Partition-by-dimension is not
  viable in pgvector (partitions share typmod; HNSW needs a fixed dimension). One `chunks`
  table with a dimensionless `vector` column supports mixed-model bots; retrieval filters by
  `bot_id` (one bot → one model → one dimension). Per-dimension HNSW tables are a possible
  later optimization behind the same store API. → [data-model](../engineering/data-model.md)
- **Two DB drivers:** async `asyncpg` at runtime, sync `psycopg` for Alembic (env.py swaps
  the URL). → [architecture](../engineering/architecture.md)
- **Pluggable providers behind Protocols, built by a factory.** Adapters take an injected
  client (unit-testable without network). → [providers](../engineering/providers.md)
- **Google & Mistral via their OpenAI-compatible endpoints** instead of dedicated SDK
  adapters (spec §7 deviation): same capability, far less code; a native adapter can replace
  the compat path later behind the same Protocol. Anthropic keeps a native adapter (no
  OpenAI-compat, no embeddings). → [providers](../engineering/providers.md)
- **Provider API keys encrypted at rest** (Fernet) and never logged. → [operations](../engineering/operations.md)
- **Strict-grounded RAG** (answer only from retrieved chunks, cite sources, else "no info").
  Behavior implemented in Phase 4. → spec §6
- **Multi-bot from day one; multi-user RBAC** (owner/editor/viewer) via FastAPI Users
  (Phase 5). → [data-model](../engineering/data-model.md)
- **Redis** for the ingestion queue (Phase 3b) and rate limiting (Phase 4). → [operations](../engineering/operations.md)
- **Tooling:** `uv` (deps/venv), `ruff` (lint), `pytest` + `testcontainers` (real Postgres).
  → [development](../engineering/development.md)

## Open / deferred

- **License** not yet chosen (needed before public OSS release). *To be confirmed.*
- Normalize provider mid-stream errors before Phase 4; add `anthropic` pin ceiling; live
  smoke-test Google/Mistral compat endpoints; decide where uploaded source files are stored
  (Phase 6). See [roadmap](roadmap.md) prerequisites.
