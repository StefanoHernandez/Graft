---
title: Project status
updated: 2026-09-11
sources: [docs/superpowers/plans/2026-09-10-graft-redesign-plan.md, git log]
source_commit: f9da461
confidence: high
---

# Project status

**As of 2026-09-11, branch `feat/graft-redesign-a` — increment A complete (tasks 0–6).**

The [redesign plan](../../docs/superpowers/plans/2026-09-10-graft-redesign-plan.md)
replaces the old phase numbering with tasks in three gated increments. Phases 1–3a are
kept; tasks 0–4 corrected them.

- 192 tests (152 unit with **no Docker**, 40 integration against a real Postgres and a
  real Redis), 0 warnings, ruff clean.
- A document can be uploaded through an authenticated admin API, is stored durably, and
  is ingested by a background worker with leases, fencing and bounded retries.
- Still no user-facing surface: retrieval, chat, widget and admin UI are increment B/C.

## Done — increment A

| Task | What landed |
|---|---|
| 0 | Unit/integration split; unit tier runs with Docker down (~1s) |
| 1 | Coded, non-leaking provider errors; embedding batch validation; prod config guards |
| 2 | Migration `0003`, durable originals, embedding fingerprint |
| 3 | Provenance-carrying parser, paragraph chunking, parser in a killable subprocess |
| 4 | Short transactions, claim/heartbeat/fencing, batched embeddings |
| 5 | Owner login (no registration route), admin API for bots and documents |
| 6 | arq worker, per-minute dispatcher, worker service in compose |

## Gate A — evidence

Run on `docker compose up` (2026-09-11) with embeddings pointed at an unreachable
endpoint: upload committed `pending` and enqueued immediately, the worker claimed it,
retried after 10s and 30s, and the sweep ended it `failed / attempts_exhausted` with
nothing left in `processing`. The run found a real bug — `WorkerSettings.redis_settings`
as a method killed the worker at boot while the app stayed healthy — now fixed and guarded
by a unit test.

**Not yet verified:** the `ready` path against a **live** embedding provider. It is
covered by integration tests with a fake embedder against real infrastructure; the live
evidence is task 11.

## Next — increment B

Tasks 7–11: exact KNN retrieval filtered by fingerprint, grounded RAG with validated
citations, the public SSE chat endpoint with per-bot origins and rate limits, the widget,
and the live RAG evaluation that produces the first real quality evidence.

See [roadmap](roadmap.md).
