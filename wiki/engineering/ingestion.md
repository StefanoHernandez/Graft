---
title: Ingestion pipeline
updated: 2026-09-10
sources: [server/graft/ingestion/*.py, server/tests/**/test_ingestion_*.py, server/tests/unit/test_parse_process.py, docs/superpowers/plans/2026-09-10-graft-redesign-plan.md]
source_commit: d54d0bb
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
- **`store.replace_document_chunks(session, document_id, chunks)`** — deletes existing
  chunks for the document, then `add_all` the new ones (idempotent re-ingest).
- **`pipeline.ingest_document(session, document, data, embedder, *, embedding_model, chunk_size=1000, chunk_overlap=200) -> int`**
  — orchestrates the above.

## `ingest_document` flow

1. set `document.status = "processing"`, flush;
2. `parse_document` → sections; `chunk_sections` → drafts (no text → `ParseError`);
3. `await embedder.embed([d.content for d in drafts], model=embedding_model)` → vectors;
4. build `Chunk` rows (`content`, `embedding`, `embedding_dim=len(vector)`,
   `position`, `chunk_metadata=draft.metadata`) via `zip(drafts, vectors, strict=True)`;
5. `replace_document_chunks`, set `ready` + `chunk_count`, **clear `error`**, commit,
   return count;
6. **on any exception**: `rollback()` (discards partial chunk writes), set
   `status="failed"`, `error=str(exc)`, commit, **re-raise**.

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
- **Task 6:** Redis enqueue on upload plus the worker and its periodic dispatcher.
- **Task 5 (upload endpoint):** sanitize `document.error` before the admin UI shows it;
  enforce the 10 MiB upload ceiling.
- `unstructured` optional parser backend (heavier extraction).
- Retrieval over chunks is **not** here — it's the RAG engine in Phase 4.
