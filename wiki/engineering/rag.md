---
title: Retrieval and RAG
updated: 2026-09-11
sources: [server/graft/rag/*.py, server/tests/integration/test_retrieval.py, server/tests/fixtures/rag/*]
source_commit: 47e3204
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

## Prompt (`rag.prompt.build_messages`)

Three things are kept apart: the product's rules, the conversation so far, and the
retrieved documents. Documents are quoted inside `<<<DOCUMENTS … DOCUMENTS>>>` and
announced as untrusted data, because a document is written by whoever uploaded it.

The bot's own `system_prompt` is included between the rules and a restatement of them,
so a prompt that says "ignore the documents" is contradicted after it is read. It can
set tone, scope or persona; it cannot delete rule 1 or the abstention.

Each source is labelled `[S1]`, `[S2]`… with its filename, page and heading, so a
citation resolves to something a visitor can check.

## Service (`rag.service.answer_question`)

Yields `delta` events, then exactly one `done` **or** one `error`.

- **No context, no call.** If nothing clears `min_score`, the answer is the fixed
  abstention, produced without spending a request on a model with nothing to work from
  (`grounding: "no_context"`).
- Sources are trimmed to the **context budget before labels are assigned**, so a label
  can never point at text the model was not shown.
- After the stream, every `[Sn]` is checked against the retrieved set. An invented label,
  or an ordinary answer that cites nothing, ends the exchange with
  `error: invalid_citation` and **no** `done` — the text was already streamed, so this
  cannot make a wrong answer right; what it refuses is to *deliver* it as a verified one.
  An answer that is exactly the abstention is valid with zero citations.
- The check proves a label exists, **not** that the sentence follows from it. Entailment
  is not something this can demonstrate, and the product must not claim it does.
- `done.citations` carries only the sources actually cited, each with an excerpt: a source
  the visitor cannot read is not a source. It also means an admin must upload only
  material meant for visitors.
- A provider failure becomes one `error` with the stable code and no `done`. Closing the
  stream closes the provider generation, so a visitor who leaves does not leave a
  generation running.

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
