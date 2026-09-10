---
title: Overview
updated: 2026-09-10
sources: [README.md, docs/superpowers/specs/2026-09-08-graft-design.md]
source_commit: 4826fc6
confidence: high
---

# Overview

**Graft** is a self-hosted, open-source framework that lets a site owner add an
LLM chatbot with **RAG** (retrieval-augmented generation) to an existing website
by pasting **one `<script>` tag** — with **no changes to the host site's backend**.

- The `<script>` injects a chat widget into a **Shadow DOM**, isolating it from
  the host page's CSS/JS regardless of the host stack.
- The widget talks over HTTP/SSE to a self-hosted **`graft-server`** (a FastAPI
  Docker service) backed by **Postgres + pgvector** and **Redis**.
- The bot answers **strictly** from documents the owner uploaded, citing sources.
- One instance is **multi-bot**; each bot chooses its own LLM/embeddings backend
  among OpenAI, Ollama, LM Studio, Anthropic, Google/Gemini, Mistral.

## What exists today (commit 4826fc6)

Built + tested: the backend **foundation** (app, config, async DB, migrations,
crypto, compose), the **provider abstraction** (all six LLM backends via a
factory), and the **ingestion pipeline** (parse → chunk → embed → store chunks).

Not yet built: the RAG retrieval + **Chat API** (Phase 4), **auth/RBAC**
(Phase 5), **Admin API/SPA** (Phase 6/7), the **browser widget** (Phase 8), and
the **async ingestion worker** (Phase 3b).

## Where to go next

- Onboarding: [agent/handoff.md](agent/handoff.md)
- How it's built: [engineering/architecture.md](engineering/architecture.md)
- Full catalog: [index.md](index.md)
- Portable card: [overview-graft.md](overview-graft.md)
