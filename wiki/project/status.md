---
title: Project status
updated: 2026-09-15
sources: [docs/superpowers/plans/2026-09-10-graft-redesign-plan.md, git log]
source_commit: 5239138
confidence: high
---

# Project status

**As of 2026-09-11, branch `feat/graft-redesign-a` — increments A, B and C complete (tasks 0–14).**

The [redesign plan](../../docs/superpowers/plans/2026-09-10-graft-redesign-plan.md)
replaces the old phase numbering with tasks in three gated increments. Phases 1–3a are
kept; tasks 0–4 corrected them.

- 320 backend tests (160 unit run with **no Docker**) plus 17 widget tests, 0 warnings,
  ruff and tsc clean. 6 live tests are deselected unless a provider key is present.
- **End to end works:** upload → durable storage → background ingestion → grounded answer
  with checkable citations, delivered to a widget on a page Graft does not serve.
- The admin surface, the reproducible deploy and the operator commands are in.
  The CI is green on a real runner (2026-09-15, commit `e07d4b0`): integration, migration
  drift, unit + lint, widget and the compose build all passed; the live job stayed skipped,
  as designed. Remaining before calling it a release: the owner's **licence decision**.

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

## Done — increment C

| Task | What landed |
|---|---|
| 12 | Admin surface at `/admin/` — the copy-desk world, plus the conversations API |
| 13 | Digest-pinned reproducible image, real readiness, operator commands, restore guide |
| 14 | CI workflow, honest README, this report |

## Gate C — evidence (2026-09-11)

Run against the **built images**, not a development server:

- `docker compose build` then `up -d`: app healthy, worker started only after it, and
  `/health/ready` reporting `database: ok, redis: ok, storage: ok`.
- The widget bundle is produced inside the image by a pinned Node stage and served at
  `/widget/graft.js` (7432 bytes).
- Owner created with the CLI inside the container; a second attempt was refused by the
  advisory lock.
- Upload → **ready in five seconds** → the chat endpoint answered with a validated
  citation, over the shared uploads volume between app and worker.
- Postgres and Redis publish no host ports in the base compose file; the dev override is
  the only place they do.
- `alembic check` inside the container: no drift between the models and the migrations.
- Every CI job was executed locally, including the unit tier with `DOCKER_HOST` pointed at
  a socket that does not exist.

**Verified since:** the CI ran on a GitHub runner on 2026-09-15 (commit `e07d4b0`) and every
automatic job passed; the live evaluation job is manual and stayed skipped.

**Still not verified:** a full dump-and-restore cycle. Restore is documented and each of its
three checks is exercised by the smoke above, but the cycle has not been performed end to end.

## Still open before a public release

1. **Licence.** Undecided, and deliberately not chosen on the owner's behalf.
2. **Five of six providers have no live evidence.** Only the Mistral path was measured.
3. **RBAC and the Refine dashboard** (tasks 15–16) are after the first release by design.

See [roadmap](roadmap.md).
