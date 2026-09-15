---
title: Wiki log
updated: 2026-09-10
sources: []
source_commit: 4826fc6
confidence: high
---

# Wiki log

## [2026-09-10] init | bootstrapped wiki
- Scope: engineering-first wiki for Graft at end of Phase 3a (commit 4826fc6).
- Pages created: overview, overview-graft, glossary, SCHEMA, log, index;
  engineering/{architecture, data-model, providers, ingestion, development, testing, operations, change-map};
  project/{status, roadmap, decisions}; agent/{context, activity, handoff}.
- Modules: covered inline in engineering pages (providers, ingestion, data-model, security).
- Project/project-docs pages populated: status, roadmap, decisions (evidence-backed from spec + code); project-docs left as future material.
- Portable overview: overview-graft.md
- Proposed for retirement: none (design spec + phase plans under docs/superpowers/ stay authoritative).
- Follow-up: run /wiki-lint to verify coverage; update pages as Phase 3b lands.

## [2026-09-10] sync | redesign planning
- Added revised spec and execution plan under docs/superpowers.
- Updated roadmap, status, decisions, context, handoff, overview-graft and activity.
- Existing engineering pages retain current implementation facts.
- work-tracker.md is absent; task checkboxes live in the detailed plan and the prioritized queue in handoff.

## [2026-09-15] correction | session id claim
- Corrected agent/context.md: the visitor session id does leave the server (returned in the
  SSE `meta` event, sent back each turn). It is a 256-bit bearer capability, not a server-side
  secret. The old wording would have misled the next contributor on a security boundary.
- Unrelated code fix in the same session: the SSE heartbeat now cancels its pending read.

## [2026-09-15] update | CI green on a real runner
- The workflow ran on GitHub for the first time (commit e07d4b0): integration, migration
  drift, unit + lint, widget and compose build all passed; the manual live job stayed skipped.
- status.md and handoff.md no longer ask the next contributor to do something already done.
  Remaining open: the licence, live evidence for five providers, a full restore cycle.

