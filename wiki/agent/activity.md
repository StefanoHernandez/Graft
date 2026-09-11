---
title: Agent activity log
updated: 2026-09-10
sources: []
source_commit: 4826fc6
confidence: high
---

# Agent activity log

Append-only. Newest last.

## [2026-09-10] bootstrap wiki
- Agent: Claude (Opus) via Claude Code.
- Trigger: owner asked to push the repo to GitHub and create a project wiki so a colleague can continue.
- Intent: engineering-first wiki + strong README, at end of Phase 3a (commit 4826fc6).
- Actions: created `README.md` and the `wiki/` tree (overview, glossary, SCHEMA, log, index;
  engineering ×8; project ×3; agent ×3, overview-graft).
- Changed wiki files: all of `wiki/**` (new) + root `README.md`.
- Validation: content derived from the spec, phase plans, and the code at 4826fc6; no source files modified.
- Decisions: documented the OpenAI-compat routing for Google/Mistral and the dimensionless-vector choice.
- Follow-up: run `/wiki-lint`; update as Phase 3b lands.

## [prior] project build (phases 1–3a)
- Built via spec → per-phase TDD plans → subagent-driven implementation/review → merge to `main`.
- History is in `git log` and `docs/superpowers/plans/`.

## [2026-09-10] redesign handoff
- Agent: Codex. Trigger: owner requested detailed redesign for colleague.
- Actions: wrote revised spec and 17-task implementation plan; linked future work from project and agent pages.
- Validation: documentation consistency and local-link checks; application tests not rerun (no local virtualenv).
- Decision: preserve existing code; deliver reliable ingestion, then RAG/widget, then minimal admin/release; full RBAC/Refine follows.
- Follow-up: colleague executes task 0 first. No source code, migrations or runtime configuration changed.

## [2026-09-11] tasks 0–14, increments A/B/C
- Agent: Claude (Opus 5), session with superpowers + ponytail + caveman + impeccable.
- Built: unit/integration split, coded provider errors, durable originals and the embedding
  fingerprint, provenance-carrying parser in a killable subprocess, short-transaction
  ingestion with leases and fencing, owner login and the admin API, arq worker and sweep,
  exact KNN retrieval, grounded answers with validated citations, the public SSE chat, the
  widget, the live evaluation, the `/admin/` surface, and the reproducible deploy.
- Validation: 320 backend tests (160 unit with no Docker), 17 widget tests, ruff and tsc
  clean, `alembic check` clean. Gates A/B/C each evidenced in project/status.md.
- Found by running rather than by testing: `WorkerSettings.redis_settings` as a method
  killed the worker at boot while the app stayed healthy; `legacy-report` counted failed
  documents as legacy data; `node --test <dir>` stopped discovering tests on Node 22.
- Decision: the admin surface is the "copy desk" world (see DESIGN.md); its direction
  contract is in `.impeccable/surfaces/`.
- Follow-up: run the CI on a real runner, choose a licence, and get live evidence for the
  five unverified providers. Tasks 15–16 (RBAC, Refine) come after the first release.
