---
title: Ingestion pipeline
updated: 2026-09-10
sources: [server/graft/ingestion/*.py, server/tests/test_ingestion_*.py, docs/superpowers/plans/2026-09-08-graft-phase-3a-ingestion-pipeline.md]
source_commit: 4826fc6
confidence: high
---

# Ingestion pipeline

`graft.ingestion` turns an uploaded document into stored, embedded chunks. Phase 3a is
the **synchronous** pipeline; Phase 3b will wrap it in a Redis-backed async worker.

## Units

- **`parsing.parse_document(filename, mime_type, data) -> str`** — PDF
  (`application/pdf` or `.pdf`) via `pypdf.PdfReader`, joining `page.extract_text()`
  with `\n`; text (`text/plain`/`text/markdown` or `.txt`/`.md`/`.markdown`) via
  `data.decode("utf-8", errors="replace")`; anything else → `ValueError`. `PdfReader` is
  imported at module level so tests can monkeypatch it.
- **`chunking.chunk_text(text, *, size=1000, overlap=200) -> list[str]`** —
  character-based sliding window; strips text and each piece; returns `[]` for empty
  input; rejects `size<=0` or `overlap` not in `[0, size)`; step = `size - overlap`.
  Provably gap-free and lossless.
- **`store.replace_document_chunks(session, document_id, chunks)`** — deletes existing
  chunks for the document, then `add_all` the new ones (idempotent re-ingest).
- **`pipeline.ingest_document(session, document, data, embedder, *, embedding_model, chunk_size=1000, chunk_overlap=200) -> int`**
  — orchestrates the above.

## `ingest_document` flow

1. set `document.status = "processing"`, flush;
2. `parse_document` → text; `chunk_text` → pieces;
3. **empty text** → clear existing chunks, set `ready`, `chunk_count=0`, commit, return 0;
4. else `await embedder.embed(pieces, model=embedding_model)` → vectors;
5. build `Chunk` rows (`content`, `embedding`, `embedding_dim=len(vector)`,
   `position`, `chunk_metadata={}`) via `zip(pieces, vectors, strict=True)`;
6. `replace_document_chunks`, set `ready` + `chunk_count`, commit, return count;
7. **on any exception**: `rollback()` (discards partial chunk writes), set
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

- **Phase 3b:** Redis enqueue on upload; a background worker that loads the document,
  builds the embedder from bot config, calls `ingest_document`, and (recommended)
  commits `status="processing"` separately for live progress. Batch `embed` for large docs.
- **Phase 6 (upload endpoint):** trim/normalize `document.error` before the admin UI shows
  it; add PDF size/time guards (pypdf on a hostile PDF is unbounded).
- `unstructured` optional parser backend (heavier extraction).
- Retrieval over chunks is **not** here — it's the RAG engine in Phase 4.
