---
title: Project status
updated: 2026-09-11
sources: [docs/superpowers/plans/2026-09-10-graft-redesign-plan.md, git log]
source_commit: 09b4e57
confidence: high
---

# Project status

**As of 2026-09-11, branch `feat/graft-redesign-a` — increments A and B complete (tasks 0–11).**

The [redesign plan](../../docs/superpowers/plans/2026-09-10-graft-redesign-plan.md)
replaces the old phase numbering with tasks in three gated increments. Phases 1–3a are
kept; tasks 0–4 corrected them.

- 301 backend tests (unit tier runs with **no Docker**) plus 17 widget tests, 0 warnings,
  ruff and tsc clean. 6 live tests are deselected unless a provider key is present.
- **End to end works:** upload → durable storage → background ingestion → grounded answer
  with checkable citations, delivered to a widget on a page Graft does not serve.
- Missing for a first release: the admin UI (task 12), reproducible deploy and restore
  (13), CI and docs (14).

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

## Gate B — evidence (2026-09-11)

First live evaluation, `mistral-embed` + `ministral-8b-latest`, 21 questions × 3 passes:
**6/6 absent questions refused every pass**, **8/8 answerable cited the right document
every pass**, **0 citations pointing at nothing**, 0 errors. The planted prompt injection
was reported as content, never obeyed; all three conflicting cases cited both sides.
Median first token 0.92s.

The calibration finding matters as much as the score: with `mistral-embed` every question
scores above 0.70, so `min_score=0.5` never triggers an abstention — every refusal came
from the model obeying the grounded prompt. Full write-up, including what this does *not*
show, in [docs/evidence/rag-baseline.md](../../docs/evidence/rag-baseline.md).

The widget was verified on a page served from another origin: an answer with an expandable
source reading `S1 · installation.md · Requirements` (providers stubbed for that run).

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

## Done — increment B

| Task | What landed |
|---|---|
| 7 | Exact KNN retrieval scoped by fingerprint; 21-case evaluation corpus |
| 8 | Grounded prompt and answer service with validated citations |
| 9 | Public SSE chat: per-bot origins, Lua rate limits, attempt persistence |
| 10 | Embeddable widget — one script tag, Shadow DOM, no runtime dependencies |
| 11 | Live evaluation script, opt-in live tests, first real baseline |

## Next — increment C

Tasks 12–14: the minimal admin UI, reproducible deploy with backup and restore, then CI
and the release documentation.

See [roadmap](roadmap.md).
