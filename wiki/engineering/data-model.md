---
title: Data model
updated: 2026-09-10
sources: [server/graft/models/*.py, server/migrations/versions/0001_initial.py, server/migrations/versions/0002_chunks.py, docs/superpowers/specs/2026-09-08-graft-design.md]
source_commit: 72e973c
confidence: high
---

# Data model

All models share one `DeclarativeBase` (`graft.models.base.Base`). `UUIDMixin` adds a
`uuid4` primary key `id`; `TimestampMixin` adds `created_at`/`updated_at`
(`server_default=now()`, non-nullable). Schema is owned by **Alembic** migrations
(`0001_initial`, `0002_chunks`), which must stay column-for-column consistent with the
models.

## Tables

### `user` (singular — FastAPI Users default table name)
From `SQLAlchemyBaseUserTableUUID` (id, email unique/indexed, hashed_password,
is_active, is_superuser, is_verified) plus **`role: str(32)`** default `"viewer"`, plus
timestamps. Auth wiring itself is Phase 5.

### `bots`
`name`, `widget_key` (unique, indexed — the public key embedded in the widget),
`allowed_origins: text[]` (CORS/origin allow-list per bot), `llm_config: jsonb`,
`embedding_config: jsonb`, `system_prompt: text`, `theme: jsonb`,
`retrieval_config: jsonb`. Each bot is an isolated knowledge base + config.

### `bot_members`
`user_id → user.id`, `bot_id → bots.id`, unique `(user_id, bot_id)`. Assigns bots to
editor users; enforced in Phase 5.

### `documents`
`bot_id → bots.id`, `filename`, `mime_type`, `status` (default `"pending"`, indexed;
lifecycle `pending → processing → ready | failed`), `error` (nullable), `chunk_count`.

Added by `0003`, all nullable so pre-0003 rows survive untouched:
- `storage_key` — path of the original under the storage root, `{bot}/{doc}/source`.
  Legacy rows have none: their original was never kept and cannot be rebuilt from chunks.
- `source_sha256` — hash of the stored original.
- `embedding_fingerprint` — the vector space the document's chunks belong to
  (see [providers](providers.md)); retrieval filters on it, so legacy `NULL` rows are
  excluded rather than deleted.
- `ingestion_run_id` + `lease_expires_at` — the fencing token and lease of the worker
  that owns the current attempt; a commit whose run id no longer matches is stale work.
- `attempt_count` — `NOT NULL DEFAULT 0`, bounds retries so nothing sits in `processing`
  forever.

### `chunks`  (Phase 3a)
`document_id → documents.id`, `bot_id → bots.id` (denormalized, indexed, for fast
per-bot filtering), `content: text`, `embedding_dim: int`, **`embedding: vector`
(dimensionless pgvector)**, `metadata: jsonb` (SQL column `metadata`, mapped to the
Python attribute **`chunk_metadata`** because Declarative reserves `metadata`),
`position: int`. **No ANN index** — exact KNN in Phase 4.

### `conversations` / `messages`  (used from Phase 4)
`conversations`: `bot_id`, `visitor_session`, `started_at`. `messages`:
`conversation_id → conversations.id`, `role`, `content`, `citations: jsonb` (nullable),
plus (from `0003`) `request_id` (nullable) and `status` — `completed | failed | cancelled`,
`NOT NULL DEFAULT 'completed'`, enforced by the `ck_messages_status` check constraint.
One chat attempt is one `request_id`: the user row is written first and settled at the
end, the assistant row only on a valid completion, so an interrupted stream is never
mistaken for an answer.

## Vector storage (spec §6.1)

`chunks.embedding` is `vector` **without a fixed dimension**. This lets bots using
different embedding models (768, 1024, 1536, 3072…) coexist in one table.

- Partition-by-dimension is **not viable** in pgvector: Postgres partitions inherit the
  parent column's typmod, and an HNSW index requires a fixed dimension.
- MVP retrieval (Phase 4) is **exact KNN**: `ORDER BY embedding <=> :q LIMIT k` filtered
  by `bot_id`. A bot has exactly one embedding model, so within a bot all vectors share
  one dimension and are comparable. `embedding_dim` is stored per chunk as a guard.
- Scale later (if needed): per-dimension tables with HNSW, behind the same store API.

**Consequence for later phases:** if a bot's embedding model (hence dimension) changes
after ingestion, its existing chunks become mixed-dimension and `<=>` will error at
query time — Phase 4/6 must force a re-embed (or guard using `embedding_dim`) on config
change.

## Migrations

- `0001_initial` — `CREATE EXTENSION vector`; creates user, bots, bot_members,
  documents, conversations, messages.
- `0002_chunks` — creates `chunks` (down_revision `0001`).
- `0003_document_lifecycle` — additive document lifecycle/provenance columns,
  `ix_documents_status`, and message attempt fields (down_revision `0002`). Reversible;
  covered by `tests/integration/test_document_lifecycle_schema.py`, which migrates a
  throwaway database in the same container so the session schema is never downgraded.
- `alembic.ini` ships an **empty** `sqlalchemy.url`: `migrations/env.py` uses an explicit
  url when a caller sets one and otherwise falls back to `DATABASE_URL`.
- Apply: `uv run alembic upgrade head` (also run automatically by the Docker entrypoint
  and by the test `migrated` fixture). Author new migrations to match the models exactly.
