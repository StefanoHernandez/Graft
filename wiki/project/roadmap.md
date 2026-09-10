---
title: Roadmap
updated: 2026-09-10
sources: [docs/superpowers/specs/2026-09-08-graft-design.md, docs/superpowers/plans/*, docs/superpowers/specs/2026-09-10-graft-redesign.md, docs/superpowers/plans/2026-09-10-graft-redesign-plan.md]
source_commit: c16dbae
confidence: high
---

# Roadmap

## Revised execution order — 2026-09-10

The owner requested a redesign and implementation handoff. The [new spec](../../docs/superpowers/specs/2026-09-10-graft-redesign.md) and [17-task plan](../../docs/superpowers/plans/2026-09-10-graft-redesign-plan.md) now define future execution: reliable documents and owner auth → RAG/chat/widget and live evaluation → minimal admin and deploy → full RBAC/Refine. Tasks are planned, not implemented. The table below preserves the original roadmap for historical mapping; it no longer defines execution order.

Graft is built one phase at a time. Each phase: a spec-derived bite-sized **TDD plan** in
`docs/superpowers/plans/`, implemented test-first, reviewed, merged to `main` when green.

| Phase | Scope | Status | Plan |
|---|---|---|---|
| 1 | Foundation: app, config, async DB, Alembic core schema, crypto, compose | ✅ | `…phase-1-foundation.md` |
| 2a | Provider abstraction + OpenAI-compatible adapter + factory | ✅ | `…phase-2a-providers-openai.md` |
| 2b | Anthropic native; Google & Mistral via OpenAI-compat | ✅ | `…phase-2b-providers.md` |
| 3a | Ingestion pipeline: chunks table, parse, chunk, embed, store | ✅ | `…phase-3a-ingestion-pipeline.md` |
| **3b** | **Redis queue + async background worker** | ⬜ next | to write |
| 4 | RAG + Chat API: exact KNN retrieval, grounded prompt, SSE stream, per-bot CORS, Redis rate limit | ⬜ | to write |
| 5 | Auth + RBAC: FastAPI Users, JWT, roles (owner/editor/viewer), `bot_members` enforcement | ⬜ | to write |
| 6 | Admin API: REST CRUD (bots, documents incl. upload, users, conversations); provider "test connection" | ⬜ | to write |
| 7 | Admin SPA: Refine + Ant Design dashboard | ⬜ | to write |
| 8 | Widget: TypeScript Shadow-DOM `graft.js` embed (launcher + chat panel, SSE, citations, theming) | ⬜ | to write |

## MVP definition (spec §12)

In: multi-bot; document upload (PDF/MD/TXT); strict-grounded RAG with citations; the six
provider backends; Postgres/pgvector; widget; admin dashboard; multi-user + RBAC;
conversation logging; per-bot `allowed_origins` + rate limit; `docker compose up`.

Out (post-MVP): auto-crawl, scheduled re-index, ingestion push API, end-user identity,
hosted SaaS mode, advanced analytics, fine-grained per-bot RBAC, per-language SDKs.

## Prerequisites captured for later phases

- **Phase 4:** normalize provider `stream_chat`/`embed` errors to `ProviderConnectionError`
  first; guard/re-embed when a bot's embedding model changes (mixed-dimension chunks break `<=>`).
- **Phase 3b:** commit `status="processing"` separately for live progress; batch embeds.
- **Phase 6:** trim `document.error` before showing it; PDF size/time guards; do not
  log/return raw provider error messages (may embed a masked key).
