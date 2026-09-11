# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Two people share one screen, and the surface is written for the second one first.

- **The operator** installs and runs the instance. Comfortable with a terminal, reads
  error codes, knows what an embedding is.
- **The person responsible for the documents** — support lead, office manager, whoever
  owns the manuals — uploads files, checks whether they became answerable, and copies the
  embed snippet to their site. They do not know what a chunk or a vector is, and nobody is
  sitting next to them to explain.

Because Graft is self-hosted per company, the admin screen is the **only** interface that
company gets. It has to explain itself.

Visitors never see the admin. They meet the product through a chat widget on a public
page and are anonymous.

## Product Purpose

Turn a pile of an organization's own documents into a chat widget on their site that
answers **only** from those documents, cites which one it used, and says it does not know
rather than inventing an answer.

Success is not "it replied". Success is a visitor who can check the answer against the
source, and an operator who can see at a glance whether an upload is answerable.

## Positioning

Graft is grounded-only and self-hosted. Two things a neighbouring product cannot
truthfully copy without rebuilding:

- **Answers are refused rather than guessed.** No retrieved context means a fixed
  refusal and no model call at all. Every claim carries a citation whose label is
  validated against the chunks actually retrieved; an answer citing a source nobody
  retrieved is discarded instead of delivered.
- **The data never leaves the company.** Postgres, Redis, the original files, and the
  provider keys all live in the customer's own `docker compose`. The only outbound traffic
  is the LLM and embedding calls the operator configured.

## Operating Context

The recurring loop is: create a bot → configure a provider → upload documents → wait for
ingestion → copy one `<script>` tag into the site → read what visitors asked.

Facts that shape the screens:

- Ingestion is **asynchronous and can fail**. A document moves `pending → processing →
  ready | failed`, is retried up to three times with backoff, and a worker or provider
  outage is a normal Tuesday, not an exception. Waiting is part of the experience, so
  progress has to be legible without a refresh.
- Failures are stable **codes**, never provider messages: `provider_auth`,
  `provider_rate_limit`, `no_extractable_text`, `attempts_exhausted`. Each needs a plain
  sentence and an obvious next move.
- Changing a bot's embedding configuration after documents exist is **refused** (409):
  old and new vectors are not comparable. Rotating just the API key stays allowed.
- Documents uploaded to a bot are quoted to anonymous visitors. The screen must say so
  before someone uploads an internal salary list.
- Provider keys go in and never come back out: responses carry only "a key is set".

## Capabilities and Constraints

- Multiple bots per instance, each with its own documents, provider config, allowed
  origins, and widget key.
- Documents: PDF (text layer only), Markdown, plain text. 10 MiB, 200 pages, 2000 chunks.
  No OCR.
- Providers are per bot: OpenAI-compatible, Anthropic, Google, Mistral, or a local
  endpoint. Only the Mistral path has live evidence (see below).
- **First release has exactly one owner account.** Editor and viewer exist in the schema
  but are refused by the API until RBAC is enforced. No public registration: the account
  is created from the command line.
- The admin token is held in memory only. A page refresh means logging in again — a
  deliberate constraint, not an oversight.
- Conversations are retained 30 days.

### Vocabulary

Confirmed with the owner: **translated by default, technical detail on request.** The
screen says "ready to answer", "processing", "needs re-uploading". Chunk counts, error
codes, and embedding fingerprints exist and are reachable, but never lead. No term is
hidden from someone who goes looking for it.

## Brand Commitments

- The product is named **Graft**. No logo, wordmark, or brand colors exist yet.
- The owner's one binding constraint on the interface: **it must not look AI-made.**
- Voice follows the vocabulary rule above: plain, specific, no cheerfulness about failure.

## Evidence on Hand

Real, measured, and safe to state:

- `docs/evidence/rag-baseline.md` — first live evaluation (2026-09-11, `mistral-embed` +
  `ministral-8b-latest`): 21 questions × 3 passes, 6/6 unanswerable questions refused each
  pass, 8/8 answerable citing the right document, zero invented citations, median first
  token 0.92s. Includes a planted prompt injection that was reported as content, never
  obeyed.
- `server/tests/fixtures/rag/` — the 21-case corpus itself.
- 301 backend tests plus 17 widget tests.

Absent, and not to be invented: no customers, no testimonials, no benchmarks against
other products, no pricing, no uptime figures, no license decision yet.

## Product Principles

1. **Verifiability over fluency.** A citation the reader can open beats a confident
   paragraph. Where the two conflict, show the source.
2. **Say "I don't know" out loud.** Refusal is a feature of the product and should read
   as one in the interface, not as an error.
3. **A stuck job is a product failure.** Anything that can fail must reach a terminal,
   visible state with a next action — never a spinner with no end.
4. **Translate, don't dumb down.** Plain language leads; the exact code is one click away
   for whoever needs it.
5. **The screen is the only manual.** Self-hosted means nobody is there to explain what a
   widget key is or why an embedding config locked.

## Accessibility & Inclusion

WCAG 2.1 AA is the working target, taken from the project's own release gate, which
requires the frontend to be verified for keyboard use and on mobile
(`docs/superpowers/plans/2026-09-10-graft-redesign-plan.md`, task 14). No user-specific
accommodation has been established beyond that.
