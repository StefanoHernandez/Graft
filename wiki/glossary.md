---
title: Glossary
updated: 2026-09-10
sources: [docs/superpowers/specs/2026-09-08-graft-design.md, server/graft]
source_commit: 4826fc6
confidence: high
---

# Glossary

- **Graft** — this project: the self-hosted framework and its `graft-server`.
- **graft-server** — the FastAPI backend (Python package `graft`), shipped as a Docker service.
- **Bot** — a configured chatbot: its own knowledge base (documents/chunks),
  provider config, widget theme, and public `widget_key`. One instance hosts many bots.
- **Widget** — the browser-side chat UI, injected by `graft.js` into a Shadow DOM
  on the host page. **Not yet implemented** (Phase 8).
- **Shadow DOM** — browser encapsulation boundary; keeps the widget's CSS/JS
  isolated from the host site (and vice-versa).
- **RAG (Retrieval-Augmented Generation)** — answer a query by retrieving relevant
  document chunks and generating an answer grounded in them.
- **Strict grounding** — the bot answers only from retrieved chunks; if nothing is
  relevant it says it has no information. Minimizes hallucination.
- **Chunk** — a slice of a parsed document plus its embedding vector; the unit of retrieval.
- **Embedding** — a fixed-length numeric vector representing text; produced by an
  embeddings model. Its length is the **dimension** (varies by model).
- **Provider** — an LLM/embeddings backend. Ids: `openai_compatible`, `anthropic`,
  `google`, `mistral`. `openai_compatible` covers OpenAI, Ollama, and LM Studio via `base_url`.
- **LLMProvider / EmbeddingProvider** — the two `Protocol`s adapters implement
  (`stream_chat` / `embed`, plus `test_connection`).
- **Factory** — `graft.providers.factory.build_llm` / `build_embedder`: turns a bot's
  config dict into a provider instance, decrypting the API key.
- **pgvector** — Postgres extension for vector columns and similarity search (`<=>`).
- **Dimensionless vector column** — the `chunks.embedding` column is `vector` with no
  fixed dimension, so bots with different embedding models coexist; retrieval is always
  per-bot (same model → same dimension). See [decisions](project/decisions.md).
- **testcontainers** — library that spins an ephemeral Docker Postgres for tests.
- **uv** — the Python dependency/venv manager used here (`uv run`, `uv sync`).
- **RBAC** — role-based access control; planned roles: owner / editor / viewer (Phase 5).
- **bot_members** — join table assigning bots to editor users (Phase 5 enforcement).
- **Phase** — a unit of work with its own plan in `docs/superpowers/plans/`; merged only after tests + review.
