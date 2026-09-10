---
title: Graft — portable overview
updated: 2026-09-10
sources: [README.md, docs/superpowers/specs/2026-09-08-graft-design.md]
source_commit: 4826fc6
confidence: high
---

# Graft — portable overview

- **What it is:** a self-hosted, open-source framework to embed an LLM chatbot
  with RAG into any existing website via a single `<script>` tag (Shadow DOM
  widget) with zero host-backend changes.
- **Why it exists:** adding a grounded, source-citing AI assistant to an existing
  site normally means invasive integration and per-stack work. Graft makes it a
  one-line, stack-agnostic drop-in, self-hosted so the owner keeps their data and
  brings their own model.
- **Current status:** early development. Foundation + provider layer + ingestion
  pipeline done and tested (46 tests green). Next: async ingestion worker
  (Phase 3b), then RAG + Chat API (Phase 4).
- **Main stack / areas:** Python 3.12 · FastAPI · SQLAlchemy 2 async · Postgres +
  pgvector · Alembic · Redis · multi-provider LLM/embeddings (OpenAI-compatible,
  Anthropic, Google, Mistral) · pypdf · Fernet · uv · pytest + testcontainers ·
  Docker Compose. Planned: Refine/Ant Design admin SPA; TypeScript Shadow-DOM widget.
- **Milestones / next steps:** Phase 3b (Redis queue + worker) → Phase 4 (retrieval,
  grounded prompt, SSE) → Phase 5 (auth/RBAC) → Phase 6 (Admin API) → Phase 7
  (Admin SPA) → Phase 8 (widget).
- **Important decisions to remember:**
  - Self-hosted standalone Docker service; host site integrates only via one script tag.
  - Single Postgres+pgvector for everything; **dimensionless** vector column, exact
    KNN per-bot (partition-by-dimension is not viable in pgvector). See
    [decisions](project/decisions.md).
  - Providers are pluggable behind Protocols; Google & Mistral use their
    OpenAI-compatible endpoints instead of dedicated SDK adapters.
  - Strict-grounded RAG; multi-bot; multi-user RBAC (owner/editor/viewer) planned.
- **Key wiki pages:** [architecture](engineering/architecture.md),
  [data-model](engineering/data-model.md), [providers](engineering/providers.md),
  [ingestion](engineering/ingestion.md), [roadmap](project/roadmap.md),
  [handoff](agent/handoff.md).

## Personal Wiki Export

- **Project:** Graft — self-hosted RAG chatbot framework for existing websites.
- **Short description:** Open-source framework; one `<script>` tag adds an LLM
  chatbot with RAG (answers from uploaded docs, cites sources) to any site,
  self-hosted, bring-your-own-model, multi-bot.
- **Current status:** Early development; backend foundation, 6-provider LLM layer,
  and ingestion pipeline built and tested. UI/widget/chat endpoint pending.
- **Role in the user's work/life:** Personal project by Stefano Paradisi
  (gransassotech.org). Da confermare oltre a questo.
- **Personal motivation:** Da confermare.
- **Technologies / skills represented:** Python/FastAPI, async SQLAlchemy,
  pgvector/RAG, LLM provider integration, Alembic, Docker, TDD with testcontainers,
  (planned) React/Refine + TypeScript widget.
- **Important next steps:** Phase 3b async ingestion worker, then Phase 4 RAG +
  Chat API.
- **Long-term notes:** 8-phase roadmap toward a shippable v1 (self-hosted OSS).
  Licence not yet chosen. Repo pushed to GitHub for collaboration.
