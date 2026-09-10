---
title: Wiki schema
updated: 2026-09-10
sources: []
source_commit: 4826fc6
confidence: high
---

# Wiki schema

This wiki is **engineering-first**: the `engineering/` pages are the authoritative
description of how the system actually works, derived from code, config, and tests.
Everything else links back to them.

## Directory layout

```
wiki/
  index.md                catalog of every page
  log.md                  chronological wiki-change log
  overview.md             short project overview
  overview-graft.md       portable project card (+ Personal Wiki Export)
  glossary.md             domain + project terms
  SCHEMA.md               this file
  engineering/            authoritative system docs
    architecture.md
    data-model.md
    providers.md
    ingestion.md
    development.md
    testing.md
    operations.md
    change-map.md         "to change X, start here"
  modules/                per-area deep dives (optional; may overlap engineering)
  project/                project state, not code
    status.md
    roadmap.md
    decisions.md
  project-docs/           reusable communication material (evidence-backed only)
  agent/                  continuity for AI/dev handoff
    context.md            durable context for whoever works next
    activity.md           append-only activity log
    handoff.md            "start here" for the next contributor
```

## Page frontmatter

Every page starts with:

```yaml
---
title: <page title>
updated: <YYYY-MM-DD>
sources: [<repo-relative files this page is derived from>]
source_commit: <short SHA the page was last verified against>
confidence: high | medium | low
---
```

## Rules

- Populate only what the code/config/tests support. Mark unknowns explicitly
  (`To be confirmed.`) rather than inventing.
- When code changes, update the affected page's `updated` + `source_commit` and
  append a line to `log.md`.
- Prefer fewer accurate pages over many generic ones.
- Never let a project page contradict an engineering page; fix engineering first.
