---
title: Project status
updated: 2026-09-10
sources: [docs/superpowers/plans/*, git log, docs/superpowers/specs/2026-09-10-graft-redesign.md, docs/superpowers/plans/2026-09-10-graft-redesign-plan.md]
source_commit: c16dbae
confidence: high
---

# Project status

## Planning update — 2026-09-10

Implementation remains at Phase 3a; documentation baseline is `c16dbae`. A [redesign plan](../../docs/superpowers/plans/2026-09-10-graft-redesign-plan.md) is ready for the colleague. Next: task 0, reproduce the baseline and separate unit/integration tests, then tasks 1–6. Test/lint success below is the earlier recorded result; it was not rerun during this planning pass because no local virtualenv was present.

**As of 2026-09-10, commit `4826fc6` — end of Phase 3a.**

- Backend foundation, provider layer (6 backends), and the synchronous ingestion
  pipeline are implemented, tested (46 tests, testcontainers Postgres), lint-clean, and
  merged to `main`.
- No user-facing surface yet: the Chat API, admin dashboard, and browser widget are
  future phases.

## Done

- **Phase 1 — Foundation:** FastAPI app + health/readiness, config, async DB, Alembic core
  schema (`0001`), Fernet crypto, docker-compose (app + pgvector + redis).
- **Phase 2a — Provider abstraction:** Protocols, config, OpenAI-compatible adapter, factory.
- **Phase 2b — Providers:** native Anthropic; Google & Mistral via OpenAI-compat; factory
  branches; decrypt-failure handling; OpenAI-adapter hardening.
- **Phase 3a — Ingestion pipeline:** `chunks` table (`0002`), parsing (pdf/md/txt),
  chunking, `ingest_document`.

## Next

- **Phase 3b — Async ingestion:** Redis queue + background worker.

## Not started

Phase 4 (RAG + Chat API), 5 (auth + RBAC), 6 (Admin API), 7 (Admin SPA), 8 (widget).

## Health

- Tests: green, pristine. Lint: clean.
- Open carry-forward items tracked in [decisions](decisions.md) and the engineering pages
  (notably: normalize provider stream errors before Phase 4; live smoke-test Google/Mistral;
  batch embeds for large docs).

See [roadmap](roadmap.md) for the full plan.
