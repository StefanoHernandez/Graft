---
title: Ingestion pipeline
updated: 2026-09-10
sources: [server/graft/ingestion/*.py, server/tests/**/test_ingestion_*.py, server/tests/unit/test_parse_process.py, docs/superpowers/plans/2026-09-10-graft-redesign-plan.md]
source_commit: 9a58098
confidence: high
---

# Ingestion pipeline

`graft.ingestion` turns an uploaded document into stored, embedded chunks. The pipeline
is still called synchronously; task 6 of the redesign plan wraps it in a Redis-backed
worker.

## Units

- **`types.py`** — `ParsedSection(text, page=None, heading=None)`,
  `ChunkDraft(content, metadata)` and `ParseError(code, *, child_returncode=None)`.
  `ParseError` subclasses `ValueError`, so callers written against the old parser still
  work. Codes: `no_extractable_text`, `unsupported_type`, `corrupt_document`,
  `too_many_pages`, `too_much_text`, `too_many_chunks`, `parse_timeout`, `parse_failed`,
  `source_missing`.
- **`parsing.parse_document(filename, mime_type, data, *, max_pages=200,
  max_chars=1_000_000) -> list[ParsedSection]`** — PDF → **one section per page**, page
  numbers 1-based; Markdown → one section per heading (a preamble keeps `heading=None`);
  TXT → a single section. Provenance is what makes a citation checkable, so it travels
  with the text. The page ceiling is checked **before** extraction. An empty result is
  always `ParseError("no_extractable_text")` — a document that produced no text is a
  failed upload, not a ready document with zero chunks.
- **`chunking.chunk_sections(sections, *, size=1000, overlap=200, max_chunks=2000)
  -> list[ChunkDraft]`** — packs whole paragraphs up to `size` **within one section**,
  never merging two pages into one chunk, and repeats the last `overlap` characters at
  the start of the next chunk so a sentence split across the seam stays retrievable. A
  paragraph longer than `size` falls back to fixed windows. Over `max_chunks` →
  `ParseError("too_many_chunks")`, raised before anything is embedded.
- **`parse_worker.parse_in_subprocess(path, filename, mime, *, timeout=30)`** — runs the
  parser in a child process. pypdf is pure Python fed by strangers' files, and a thread
  cannot be stopped: a timeout that leaves the work running is not a timeout. The child
  always exits 0 with one JSON object (`{"sections": [...]}` or `{"error": code}`); the
  parent kills **and reaps** it on timeout or cancellation.
- **`jobs.py`** — ownership of one attempt, one short transaction per call, no provider
  call inside any of them: `claim_document` (a single UPDATE decides the winner, refuses
  a document whose `attempt_count` is exhausted), `heartbeat_document` (extends the lease,
  `False` once the run no longer owns the row), `finish_document` (locks the row
  `FOR UPDATE`, re-checks run id **and** the bot's current embedding fingerprint, then
  replaces chunks and marks `ready` atomically), `fail_document` (only the owning run).
- **`store.replace_document_chunks(session, document_id, chunks)`** — deletes existing
  chunks for the document, then `add_all` the new ones (idempotent re-ingest).
- **`pipeline.ingest_document(sessionmaker, document_id, embedder, *, embedding_model,
  storage_root, chunk_size=1000, chunk_overlap=200, batch_size=32, lease_seconds=120,
  heartbeat_seconds=30, parse_timeout=30, max_attempts=3) -> int`** — orchestrates the
  above. It takes a **sessionmaker and an id**, not a live ORM object: the attempt
  outlives any one session, and a session held open across a provider call is the lock
  we are avoiding.

## `ingest_document` flow

1. `claim_document` → run id, or `ClaimFailed` if another worker owns it or the
   attempts are exhausted; read filename, mime, `storage_key` and the bot's fingerprint
   in the same short transaction;
2. start the heartbeat task (cancelled in `finally`);
3. no `storage_key` → `ParseError("missing_source")`, **before** any provider call;
4. `parse_in_subprocess` on the stored original → sections; `chunk_sections` → drafts;
5. `_embed_in_batches` (32 per call) — rejects a batch that returns the wrong count or
   changes dimension, which would poison every later `<=>` for that bot;
6. `finish_document` publishes atomically; a `False` means the document was reclaimed,
   deleted or reconfigured mid-flight, and the work is dropped rather than forced through;
7. **on an exception**: `fail_document(code)` — the stable code, never a provider
   message — then re-raise. **Cancellation is not a failure**: the document stays
   `processing` so the lease expires and the dispatcher retries it.

## Worker (`queue.py`, `worker.py`)

- `enqueue_document(redis, document_id)` sends **an id and nothing else** — file bytes
  would bloat Redis and provider keys have no business leaving the database. The job id
  is stable (`ingest:{document_id}`), so a duplicate enqueue is a no-op.
- `ingest_job(ctx, document_id)` skips a document that is already `ready` (a replay after
  a lost ack) or gone, then runs the pipeline with the embedder built from the bot's
  config with **`max_retries=0`** — the job owns retry, and stacking SDK retries under it
  multiplies the wall clock and the bill.
- Retry policy lives in the worker, not the pipeline: a **permanent** failure (bad key,
  bad model, unparseable file) fails the document at once; a **transient** one puts it
  back in `pending` and defers 10s then 30s, with the attempt still counted so three
  tries means three tries.
- `dispatch_pending(ctx)` runs every minute (and at startup): it re-enqueues `pending`
  documents and expired leases, and marks `attempts_exhausted` on anything that can never
  be claimed again. This is what makes a Redis outage cost latency instead of a document.
- `WorkerSettings`: `max_jobs=1`, `job_timeout=600`, `keep_result=0`; run it with
  `uv run arq graft.ingestion.worker.WorkerSettings`.
- The upload endpoint (and the retry endpoint) enqueue **after** the commit and never
  fail the request when Redis is unreachable.
- `WorkerSettings` entries are read by arq as plain attributes and never called, so
  `redis_settings` is a value, not a method. Getting that wrong does not fail at import —
  it kills the worker at boot, inside a container, where nobody is watching.
  `tests/unit/test_worker_settings.py` guards it.

### Observed on a real stack (2026-09-11, commit b8dc0fd + fix)

`docker compose up`, upload through the admin API, embeddings pointed at an
unreachable endpoint: upload committed `pending` and enqueued immediately; the worker
claimed it, retried after **10s** then **30s**, and the 60-second sweep marked it
`failed / attempts_exhausted`. Nothing was left in `processing`. The `ready` path is
covered by integration tests against a real Postgres and Redis with a fake embedder —
it has **not** been run against a live embedding provider yet (that is task 11).

## Contract & invariants

- The caller passes an **already-persisted** `Document` (committed row) and **cedes
  session ownership** to `ingest_document` (it commits on success and on failure).
- The **embedder is dependency-injected** — the caller (Phase 3b worker / Phase 6
  endpoint) builds it from the bot's `embedding_config` via `providers.factory.build_embedder`
  and passes the model name. This keeps the pipeline unit-testable with a fake embedder.
- Success is atomic (delete-old + insert-new + status in one transaction → no partial
  chunks). Failure leaves 0 partial chunks and a `failed` document row.
- `zip(..., strict=True)` catches an embedder returning the wrong number of vectors.

## Not yet done (later phases)

- **Task 4:** short transactions with a claim/heartbeat/fencing token, batched embeds,
  and `parse_in_subprocess` wired into the pipeline (it exists but the pipeline still
  parses in-process). A failed re-ingest currently leaves the previous chunks in the
  table — deliberate, with `status` keeping them out of retrieval.
- **Task 12 (admin UI):** show `document.error` codes in a readable form.
- `unstructured` optional parser backend (heavier extraction).
- Retrieval over chunks is **not** here — it's the RAG engine in Phase 4.
