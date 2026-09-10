---
title: Graft wiki — index
updated: 2026-09-10
sources: []
source_commit: 4826fc6
confidence: high
---

# Graft wiki — index

Engineering-first documentation for **Graft**. New here? Start with
[agent/handoff.md](agent/handoff.md).

## Overview
- [overview.md](overview.md) — what Graft is, in short
- [overview-graft.md](overview-graft.md) — portable project card
- [glossary.md](glossary.md) — terms
- [SCHEMA.md](SCHEMA.md) — how this wiki is organized
- [log.md](log.md) — wiki change log

## Engineering (authoritative)
- [architecture.md](engineering/architecture.md) — components, runtime, deployment
- [data-model.md](engineering/data-model.md) — tables, migrations, vector storage
- [providers.md](engineering/providers.md) — LLM/embeddings Protocols, adapters, factory
- [ingestion.md](engineering/ingestion.md) — parse → chunk → embed → store
- [development.md](engineering/development.md) — setup, commands, conventions
- [testing.md](engineering/testing.md) — test suite + fixtures
- [operations.md](engineering/operations.md) — running, config, migrations, gaps
- [change-map.md](engineering/change-map.md) — "to change X, start here"

## Project
- [status.md](project/status.md) — current state
- [roadmap.md](project/roadmap.md) — the 8-phase plan + MVP definition
- [decisions.md](project/decisions.md) — key choices and why

## Agent / continuity
- [handoff.md](agent/handoff.md) — start here to continue the work
- [context.md](agent/context.md) — durable context + gotchas
- [activity.md](agent/activity.md) — activity log

## Reference (in repo, outside the wiki)
- Design spec: `docs/superpowers/specs/2026-09-08-graft-design.md`
- Phase plans: `docs/superpowers/plans/*.md`
- Code: `server/graft/`
