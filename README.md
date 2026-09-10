# Graft

**Self-hosted, open-source framework to add an LLM chatbot with RAG to any existing website — with one line of HTML and zero changes to the host site's backend.**

A site owner drops a single `<script>` tag into their page; it injects a chat widget isolated in a **Shadow DOM** (so it never clashes with the host site's CSS/JS, whatever the stack — Angular, Spring, Node, WordPress, static HTML). The widget talks directly to a self-hosted **Graft server** (a Docker service) that answers **strictly from documents the site owner uploaded**, citing its sources.

> Status: **early development.** The backend foundation, the multi-provider LLM/embeddings layer, and the document-ingestion pipeline are built and tested. The RAG chat endpoint, auth, admin dashboard, and the browser widget are **not yet implemented** — see [Roadmap & status](#roadmap--status).

## Why Graft

- **One-line install, no backend changes.** The only integration point on the host site is one `<script>` tag. All logic lives in the self-hosted Graft server.
- **Stack-agnostic.** Shadow DOM isolation means the widget works on any site that serves HTML.
- **Own your data.** Self-hosted; bring your own LLM (cloud API key or a local model). Uploaded documents and provider keys stay on your infrastructure.
- **Grounded answers.** Strict RAG: the bot answers only from retrieved chunks and says "I don't know" otherwise.
- **Multi-bot, multi-provider.** One instance serves many bots; each bot picks its own LLM/embeddings backend among OpenAI, Ollama, LM Studio, Anthropic, Google/Gemini, Mistral.

## Architecture at a glance

```
Host site (any stack, backend UNCHANGED)
  <script src=".../widget/graft.js" data-graft-bot="KEY"></script>   [widget: not built yet]
        │  HTTP / SSE   (CORS via per-bot allowed_origins)
        ▼
  graft-server  (FastAPI, Docker)
   • Chat API (public, SSE)          [Phase 4 — not built]
   • Admin API + SPA (Refine, JWT)   [Phase 6/7 — not built]
   • Ingestion pipeline  ✅ built
   • RAG engine                       [Phase 4 — not built]
   • Provider adapters  ✅ built  (OpenAI-compat | Anthropic | Google | Mistral)
        │
        ▼
  Postgres + pgvector   ✅        Redis   (rate limit + ingestion queue) [worker: Phase 3b]
```

Full design: [docs/superpowers/specs/2026-09-08-graft-design.md](docs/superpowers/specs/2026-09-08-graft-design.md).

## Tech stack

| Area | Choice |
|---|---|
| Backend | Python 3.12, **FastAPI**, uvicorn |
| Data + vectors | **Postgres + pgvector** (single engine; dimensionless `vector` column, exact KNN) |
| ORM / migrations | SQLAlchemy 2 (async, `asyncpg`) + **Alembic** (sync `psycopg`) |
| LLM/embeddings | pluggable adapters — `openai` (OpenAI/Ollama/LM Studio), `anthropic`; Google & Mistral via their OpenAI-compatible endpoints |
| Doc parsing | `pypdf` (PDF), plain Markdown/text |
| Secrets | `cryptography` Fernet (provider keys encrypted at rest) |
| Queue | Redis (worker in Phase 3b) |
| Tooling | **uv** (deps/venv), **ruff** (lint), **pytest** + **testcontainers** |
| Deploy | `docker compose` (app + pgvector + redis) |

## Repository layout

```
server/                     # the Python backend (package `graft`)
  graft/
    main.py  config.py  db.py        # app factory, settings, async DB
    api/health.py                    # /health, /health/ready
    security/crypto.py               # Fernet encrypt/decrypt for provider keys
    models/                          # SQLAlchemy models (see wiki/engineering/data-model.md)
    providers/                       # LLM/embeddings abstraction + adapters + factory
    ingestion/                       # parse → chunk → embed → store pipeline
  migrations/                        # Alembic (0001 core schema, 0002 chunks)
  tests/                             # pytest suite (testcontainers Postgres)
  Dockerfile  entrypoint.sh  pyproject.toml
docker-compose.yml                   # app + db(pgvector) + redis
docs/superpowers/specs/              # the design spec (source of truth)
docs/superpowers/plans/              # per-phase implementation plans (TDD, bite-sized)
wiki/                                # engineering-first project wiki — START HERE to onboard
```

## Getting started

Prerequisites: **Python ≥ 3.12**, **[uv](https://docs.astral.sh/uv/)**, **Docker** (running — the test suite spins a real Postgres via testcontainers).

### Run the tests (fastest way to confirm your setup)

```bash
cd server
uv run pytest -v
```

`uv run` auto-syncs the virtualenv from `pyproject.toml`. The suite starts an ephemeral `pgvector/pgvector:pg16` container, applies the Alembic migrations, and exercises the models, providers, and ingestion pipeline. It must be green and warning-free.

### Run the stack with Docker

```bash
cp .env.example .env
# generate a Fernet key and put it in .env as ENCRYPTION_KEY:
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
docker compose up
```

`app` runs `alembic upgrade head` then serves on **http://localhost:8000**. Check `GET /health` → `{"status":"ok"}` and `GET /health/ready` (DB probe) → `{"status":"ready"}`.

### Environment variables (`.env`)

| Var | Meaning |
|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://…` (runtime); Alembic swaps to `+psycopg` internally |
| `REDIS_URL` | `redis://redis:6379/0` |
| `JWT_SECRET` | auth signing secret (used from Phase 5) |
| `ENCRYPTION_KEY` | **Fernet key** — encrypts provider API keys at rest; required in prod |
| `CORS_ORIGINS` | JSON list; base CORS (per-bot `allowed_origins` is the real gate, Phase 4) |
| `APP_ENV` | `dev` / `prod` |

`.env` is git-ignored — never commit real keys. Only `.env.example` (placeholders) is tracked.

## Roadmap & status

> **Planning update (2026-09-10):** the [revised design](docs/superpowers/specs/2026-09-10-graft-redesign.md) and [implementation plan for the next contributor](docs/superpowers/plans/2026-09-10-graft-redesign-plan.md) supersede the future execution order below. No new functionality is implemented by this documentation update. Start with plan task 0.

Built iteratively, one phase at a time; each phase has a plan in `docs/superpowers/plans/` and lands on `main` only after tests pass and review.

| Phase | Scope | Status |
|---|---|---|
| 1 — Foundation | FastAPI app, config, async DB, Alembic core schema, Fernet crypto, compose | ✅ merged |
| 2a — Provider abstraction | Protocols, config, OpenAI-compatible adapter, factory | ✅ merged |
| 2b — More providers | Anthropic (native); Google & Mistral via OpenAI-compat | ✅ merged |
| 3a — Ingestion pipeline | chunks table, parsing, chunking, `ingest_document` | ✅ merged |
| **3b — Async ingestion** | Redis queue + background worker | ⬜ next |
| 4 — RAG + Chat API | retrieval (exact KNN), grounded prompt, SSE streaming, rate limit | ⬜ |
| 5 — Auth + RBAC | FastAPI Users, JWT, roles (owner/editor/viewer), `bot_members` | ⬜ |
| 6 — Admin API | REST CRUD (bots, docs, users, conversations) | ⬜ |
| 7 — Admin SPA | Refine + Ant Design dashboard | ⬜ |
| 8 — Widget | TypeScript Shadow DOM embed (`graft.js`) | ⬜ |

Current commit sits at end of **Phase 3a**. See [wiki/project/status.md](wiki/project/status.md) and [wiki/project/roadmap.md](wiki/project/roadmap.md).

## Continuing the work (for a colleague)

1. Read [wiki/agent/handoff.md](wiki/agent/handoff.md) — the "start here" for the next contributor.
2. Skim the [design spec](docs/superpowers/specs/2026-09-08-graft-design.md) and the [wiki](wiki/index.md).
3. The next unit of work is **Phase 3b**; the plans in `docs/superpowers/plans/` show the house style (spec → bite-sized TDD plan → implement → review → merge). Follow the same shape for new phases.
4. Conventions: every change is TDD, `uv run ruff check .` clean, test output pristine, migrations match models exactly, provider keys never logged. See [wiki/engineering/development.md](wiki/engineering/development.md).

## License

Intended as open source. License not yet chosen — **To be confirmed** by the project owner before public release.
