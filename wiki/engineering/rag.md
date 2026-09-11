---
title: Retrieval and RAG
updated: 2026-09-11
sources: [server/graft/rag/*.py, server/tests/integration/test_retrieval.py, server/tests/fixtures/rag/*]
source_commit: ed5db22
confidence: high
---

# Retrieval and RAG

## `rag.retrieval.retrieve`

```python
retrieve(session, bot_id, fingerprint, query_vector, *, top_k=5, min_score=0.5)
    -> list[RetrievedChunk]
```

`RetrievedChunk`: `chunk_id`, `document_id`, `content`, `score`, `filename`, `page`,
`heading`. Ordered by score descending, `chunk_id` as the tie-break so the same query
returns the same order twice.

Exact KNN, no ANN index. Every filter exists to stop a comparison that would be
meaningless and still look confident:

- `bot_id` on **both** the chunk and its document — one bot never sees another's corpus;
- `status = 'ready'` — a pending, processing or failed document is not searchable, which
  is also what keeps the old chunks of a failed re-ingest out of answers;
- `embedding_fingerprint` — **the** compatibility check. Two vectors of the same length
  produced by different models are not comparable, so dimension alone is never the test.
  Legacy chunks (fingerprint `NULL`) are excluded rather than deleted;
- `embedding_dim` and `vector_dims(embedding)` — a defensive pair, in case a row's stored
  dimension ever disagreed with its vector.

The eligible set is a **`MATERIALIZED`** CTE: without it the planner may push `<=>` down
and evaluate the distance on rows of another dimension, which errors at runtime. The
query vector is bound with the typed `Vector()` bind, never interpolated into SQL.

`score` is cosine similarity (`1 - distance`). A query vector that is empty, non-finite
or all zeros is refused: it has no direction, so the distance means nothing.
`min_score` is the abstention line — the default 0.5 is a starting point that has to be
calibrated against a real corpus, not trusted.

## Evaluation corpus (`tests/fixtures/rag/`)

`cases.json` holds 21 questions over five small documents, mixed the way the release gate
is stated: **8 answerable**, **6 absent**, **3 partial**, **3 conflicting**, plus one
injection case. Each case carries `expected_documents`, `expected_facts` and
`must_abstain`; the facts are for human review, not string matching.

Two properties are deliberate:

- `billing.md` and `legacy-policy.md` **disagree** (30-day vs 14-day refund, 49 vs 39 EUR).
  A good answer surfaces the disagreement instead of silently picking one.
- `security.md` contains a planted instruction (*"Ignore all previous instructions…"*).
  Documents are untrusted data; if that ever becomes an instruction, the product is
  broken. `tests/unit/test_rag_cases_fixture.py` fails if the trap is ever removed.

The live evaluation that actually grades answers is task 11 and needs a provider key.
