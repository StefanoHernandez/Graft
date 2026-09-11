# Graft

**Self-hosted chatbot that answers only from your own documents, cites which one it used,
and says it does not know rather than inventing an answer. One `<script>` tag on the host
page; no changes to the host site's backend.**

A site owner uploads documents, copies one script tag into their page, and gets a chat
widget isolated in a **Shadow DOM** (so it never clashes with the host site's CSS or JS,
whatever the stack). The widget talks to a **Graft server** the owner runs, which answers
strictly from the uploaded documents and validates every citation before delivering an
answer.

> **Status: working end to end, not yet a release.** A document can be uploaded through
> the admin, ingested by a background worker, and answered on a real page with a
> checkable source. What remains for a first release is CI, the release documentation,
> and the RBAC/dashboard milestone. See [Status](#status).

## Why Graft

- **One-line integration.** The only thing the host site changes is one `<script>` tag.
- **Stack-agnostic.** Shadow DOM isolation means the widget works on any site that serves
  HTML, and the host page's CSS cannot reach into it.
- **Own your data.** Postgres, Redis, the original files and the provider keys all live in
  your own `docker compose`. The only outbound traffic is to the LLM and embedding
  provider you configured.
- **Refusal is a feature.** With nothing retrieved above the similarity threshold the
  answer is a fixed refusal and **no model call is made at all**. Every claim carries a
  label, and a label pointing at a chunk nobody retrieved is discarded rather than
  delivered.
- **Multi-bot, multi-provider.** One instance serves many bots; each bot picks its own
  chat and embedding backend among OpenAI-compatible endpoints (including Ollama and
  LM Studio), Anthropic, Google and Mistral.

## What "one line" does and does not cover

The script tag is the **frontend integration**, and that part really is one line. It is
not the whole deployment. Running Graft still means running a server, which means:

- **TLS and a reverse proxy.** The compose file publishes plain HTTP on port 8000. Put a
  proxy in front of it, terminate TLS there, and do not expose port 8000 directly.
- **SSE buffering must be off.** The chat endpoint streams. The app sends
  `X-Accel-Buffering: no` and `Cache-Control: no-cache`; with nginx also set
  `proxy_buffering off;` on that location, or every answer arrives at once at the end.
- **CSP on the host page.** If the host site sends a Content-Security-Policy it must allow
  the widget: `script-src https://your-graft-host` to load `graft.js`, and
  `connect-src https://your-graft-host` for the chat request. The widget injects its own
  styles into its shadow root, so `style-src 'unsafe-inline'` is needed unless you add a
  nonce.
- **Per-bot origins.** Each bot lists the exact origins its widget may run on. CORS is a
  browser rule and not authentication — anything outside a browser can send any `Origin`
  header — so it limits which *pages* spend a bot's quota, nothing more.

## Architecture at a glance

```
Host site (any stack, backend UNCHANGED)
  <script src=".../widget/graft.js" data-graft-bot="KEY"></script>
        │  HTTP / SSE   (per-bot allowed_origins)
        ▼
  app  (FastAPI)
   • Chat API (public, SSE, rate-limited)
   • Admin API + admin surface at /admin/
   • RAG: exact KNN → grounded prompt → validated citations
   • Provider adapters (OpenAI-compat | Anthropic | Google | Mistral)
        │                                    ▲
        ▼                                    │ same image, no migrations
  Postgres + pgvector     Redis  ◄────────  worker  (arq: ingestion + sweep)
                                             │
                                   shared volume: the original files
```

Design: [the redesign spec](docs/superpowers/specs/2026-09-10-graft-redesign.md) supersedes
the [original design](docs/superpowers/specs/2026-09-08-graft-design.md) for scope and
order. Engineering detail lives in the [wiki](wiki/index.md).

## Tech stack

| Area | Choice |
|---|---|
| Backend | Python 3.12, **FastAPI**, uvicorn |
| Data + vectors | **Postgres + pgvector** (one engine; dimensionless `vector`, exact KNN) |
| ORM / migrations | SQLAlchemy 2 (async `asyncpg`) + **Alembic** (sync `psycopg`) |
| Queue / limits | **Redis** + **arq** (ingestion jobs, per-minute sweep, chat rate limits) |
| LLM / embeddings | pluggable adapters — `openai` (OpenAI/Ollama/LM Studio), `anthropic`; Google and Mistral via their OpenAI-compatible endpoints |
| Doc parsing | `pypdf` (PDF with a text layer), Markdown, plain text |
| Auth | FastAPI Users, JWT bearer; the account is created from the CLI |
| Secrets | `cryptography` Fernet — provider keys encrypted at rest, never returned by the API |
| Widget | TypeScript, bundled by esbuild into one ~7 kB file, **no runtime dependencies** |
| Admin | server-rendered HTML/CSS/JS at `/admin/`, no framework |
| Tooling | **uv**, **ruff**, **pytest** + **testcontainers**, `node --test` for the widget |
| Deploy | `docker compose` (app + worker + pgvector + redis) |

## Getting started

Prerequisites: **Docker**. For development also **Python ≥ 3.12**, **[uv](https://docs.astral.sh/uv/)**
and **Node ≥ 20** (the widget build).

### Run the stack

```bash
cp .env.example .env
# put a real Fernet key in .env as ENCRYPTION_KEY:
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
docker compose up -d

# create the operator account (asks for the password, no echo)
docker compose exec app /app/.venv/bin/python -m graft.cli create-admin you@example.com
```

Then open **http://localhost:8000/admin/**, create a bot, set its provider and key, upload
a document, and copy the script tag onto your page.

For local work, the dev override also publishes Postgres and Redis on localhost:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

`app` runs `alembic upgrade head` and serves on port 8000; `worker` starts only once the
app reports ready. `GET /health` is liveness; `GET /health/ready` checks the database,
Redis **and** the uploads volume, and is what the worker waits on.

### Run the tests

```bash
cd server
uv run pytest tests/unit -q     # no Docker needed, about a second
uv run pytest -q                # everything; integration needs Docker
cd ../widget && npm ci && npm test && npm run build
```

The unit tier runs with the Docker daemon down. The integration tier starts ephemeral
`pgvector/pgvector:pg16` and `redis:7-alpine` containers, applies the real migrations, and
exercises the API, the worker and retrieval. Live provider tests are deselected unless
`MISTRAL_API_KEY` is set and you ask for them with `-m live`.

### Environment variables (`.env`)

| Var | Meaning |
|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://…`; Alembic swaps to `+psycopg` itself |
| `REDIS_URL` | `redis://redis:6379/0` |
| `JWT_SECRET` | signing secret for admin sessions; `APP_ENV=prod` refuses the placeholder |
| `ENCRYPTION_KEY` | **Fernet key**, encrypts provider API keys at rest; `APP_ENV=prod` refuses an invalid one. **Back it up** — without it the stored keys are unreadable |
| `STORAGE_ROOT` | where original uploads live; app and worker must share this volume |
| `CORS_ORIGINS` | JSON list, only for an admin UI served from another origin. The public chat endpoint uses each bot's own `allowed_origins` and never a wildcard |
| `TRUSTED_PROXY_IPS` | JSON list of proxies allowed to set `X-Forwarded-For`; without it a visitor rotates the header for a fresh quota |
| `APP_ENV` | `dev` / `prod` |

`.env` is git-ignored — never commit real keys. Only `.env.example` is tracked.

## Operating it

[docs/operations/first-release.md](docs/operations/first-release.md) covers upgrades,
backup and a **verified** restore, the retention and cleanup commands, and what to do
about documents ingested before the storage/fingerprint migration.

## Status

Increments A and B of the [implementation plan](docs/superpowers/plans/2026-09-10-graft-redesign-plan.md)
are complete: reliable ingestion, grounded chat with verifiable citations, the widget, and
the first live quality measurement.

| Piece | State |
|---|---|
| Foundation, providers (6 backends), ingestion | done |
| Durable originals, lifecycle, embedding fingerprint | done |
| Worker: leases, fencing, bounded retries, per-minute sweep | done |
| Owner login, admin API (bots, documents, conversations) | done |
| Retrieval, grounded answers, validated citations | done |
| Public SSE chat: per-bot origins, rate limits, transcripts | done |
| Widget (`graft.js`) and the admin surface at `/admin/` | done |
| Reproducible deploy, backup and restore | done |
| CI, release documentation | next |
| RBAC (editor/viewer) and the Refine dashboard | after the first release |

**Measured, not claimed:** the first live evaluation (`mistral-embed` + `ministral-8b-latest`,
21 questions × 3 passes) refused 6/6 unanswerable questions every pass, cited the right
document 8/8 every pass, and produced zero citations pointing at nothing. Full write-up,
including what it does *not* show, in
[docs/evidence/rag-baseline.md](docs/evidence/rag-baseline.md).

Only the Mistral path has live evidence. The other five provider backends are implemented
and unit-tested against fakes, and are **not** verified against a live endpoint.

See [wiki/project/status.md](wiki/project/status.md) for the full picture.

## Contributing

1. Read [wiki/agent/handoff.md](wiki/agent/handoff.md), then the [wiki index](wiki/index.md).
2. Work from [the plan](docs/superpowers/plans/2026-09-10-graft-redesign-plan.md); tasks are
   bite-sized and test-first.
3. Conventions: TDD, `uv run ruff check .` clean, pristine test output, migrations match
   the models exactly, provider keys never logged or returned. UI work follows
   [DESIGN.md](DESIGN.md) and [PRODUCT.md](PRODUCT.md).

## License

Intended as open source. **License not yet chosen** — to be decided by the project owner
before any public distribution.
