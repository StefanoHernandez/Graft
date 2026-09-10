---
title: Change map — "to change X, start here"
updated: 2026-09-10
sources: [server/graft/**, server/migrations/**]
source_commit: 4826fc6
confidence: high
---

# Change map

Where to start for common changes.

| I want to… | Start here |
|---|---|
| Add/rename a config setting | `graft/config.py` (`Settings`) + `.env.example` + `README.md` env table |
| Change the DB schema | add a model field in `graft/models/*.py` **and** a new `migrations/versions/000N_*.py` (match exactly); update [data-model](data-model.md) |
| Add a new table | new `graft/models/<name>.py` + export in `models/__init__.py` + migration + a round-trip test |
| Add/adjust an LLM or embeddings backend | `graft/providers/` — add an adapter (or a factory branch for an OpenAI-compatible endpoint) in `factory.py`; add DI-fake tests; see [providers](providers.md) |
| Change how documents are parsed | `graft/ingestion/parsing.py` (dispatch by mime/extension) |
| Change chunking (size/overlap/strategy) | `graft/ingestion/chunking.py`; defaults also flow through `pipeline.ingest_document` params |
| Change the ingest flow / status handling | `graft/ingestion/pipeline.py` (+ `store.py`) |
| Add an HTTP endpoint | new router under `graft/api/`, include it in `graft/main.py:create_app` |
| Change secret handling | `graft/security/crypto.py` (Fernet); keys resolved in `providers/factory.py:_resolve_key` |
| Change how tests get a database | `server/tests/conftest.py` (`pg`, `migrated`, `db_engine`, `db_session`) |
| Change deployment | `docker-compose.yml`, `server/Dockerfile`, `server/entrypoint.sh` |

## Building the next phase

Each phase has a plan in `docs/superpowers/plans/`. The upcoming ones:

- **Phase 3b (async ingestion):** add `graft/ingestion/queue.py` + a worker entrypoint;
  enqueue a document id on upload; the worker builds the embedder via
  `providers.factory.build_embedder(EmbeddingConfig(**bot.embedding_config))` and calls
  `ingest_document`. Redis service already exists in compose.
- **Phase 4 (RAG + Chat API):** a `graft/rag/` retrieval module doing exact KNN
  (`ORDER BY embedding <=> :q LIMIT k WHERE bot_id = :b`), a grounded-prompt builder, and
  a public SSE `POST /api/v1/chat` router with per-bot origin check + Redis rate limit.
  **Before this ships, normalize provider stream errors** (see [providers](providers.md)).
- **Phase 5+:** FastAPI Users auth + RBAC, Admin API, Refine SPA, the widget.
