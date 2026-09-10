---
title: Providers (LLM / embeddings)
updated: 2026-09-10
sources: [server/graft/providers/*.py, server/tests/test_providers_*.py, docs/superpowers/specs/2026-09-08-graft-design.md]
source_commit: 2f41671
confidence: high
---

# Providers (LLM / embeddings)

`graft.providers` is a pluggable abstraction over LLM chat + embeddings backends.
Callers depend only on two `Protocol`s; a **factory** builds a concrete adapter from a
bot's config, decrypting the API key.

## Protocols (`providers/base.py`)

- `LLMProvider`: `stream_chat(messages, *, model, temperature=0.0, max_tokens=None) -> AsyncIterator[str]`
  (async generator yielding **non-empty content deltas**) and `async test_connection()`.
- `EmbeddingProvider`: `embed(texts, *, model) -> list[list[float]]` (one vector per input,
  in order) and `async test_connection()`.
- `ChatMessage` = `TypedDict{role, content}`.
- Errors: `ProviderError(code, *, retryable)`, `ProviderConnectionError(ProviderError)`.
  `str(exc)` **is** the code — SDK messages can embed the API key or the request body, so
  they never reach an admin, a visitor, or a log. `provider_error(exc, *, connection=False)`
  normalizes any SDK exception; it is idempotent and lets `CancelledError`/`GeneratorExit`
  through untouched (both are `BaseException`), so a disconnected visitor is not an outage.
- Codes: `provider_auth`, `provider_rate_limit`, `provider_timeout`, `provider_unavailable`,
  `provider_invalid_response`, `provider_config`. Retryable: rate-limit, timeout, unavailable.
  Classification matches SDK class names first (openai and anthropic share the names but
  no base class), then HTTP status: 400/404 → `provider_config`, other 4xx →
  `provider_invalid_response`, 5xx → `provider_unavailable`. An **unknown** exception is
  `provider_unavailable` but **not** retryable — a blind retry doubles the bill.
- `validate_vectors(vectors, *, expected)` rejects a batch before it can be stored:
  wrong count, empty or ragged dimensions, non-finite values, zero norm.

Both Protocols are `@runtime_checkable`. Adapters take a **dependency-injected client**
and make no network call at construction — which is what makes them unit-testable with
fakes (no network, no HTTP mocking).

## Config (`providers/config.py`)

`LLMConfig` / `EmbeddingConfig` (pydantic): `provider`, `model`, `base_url: str|None`,
`api_key: str|None`, `api_key_encrypted: bool = True`. These map onto a bot's
`llm_config` / `embedding_config` JSON.

## Adapters

| provider id | LLM adapter | Embeddings | Notes |
|---|---|---|---|
| `openai_compatible` | `OpenAICompatibleLLM` | `OpenAICompatibleEmbedder` | Covers **OpenAI, Ollama, LM Studio** — only `base_url` differs |
| `anthropic` | `AnthropicLLM` (native `anthropic` SDK) | — (none) | Chat only; Anthropic has no embeddings API |
| `google` | `OpenAICompatibleLLM` | `OpenAICompatibleEmbedder` | Routed to Gemini's OpenAI-compatible endpoint |
| `mistral` | `OpenAICompatibleLLM` | `OpenAICompatibleEmbedder` | Routed to Mistral's OpenAI-compatible endpoint |

- **OpenAI-compatible** (`providers/openai_compatible.py`) wraps `openai.AsyncOpenAI`.
  `stream_chat` awaits `chat.completions.create(stream=True)` and yields
  `chunk.choices[0].delta.content` (skips chunks with no choices / empty deltas;
  forwards `max_tokens` only when set). `embed` returns `resp.data` embeddings
  **sorted by `index`** (order-robust), then runs `validate_vectors`. `stream_chat`,
  `embed` and `test_connection` all normalize failures through `provider_error`; the
  `stream_chat` try spans the whole stream, so a mid-stream failure is coded too.
  `aclose()` closes the underlying httpx client.
- **Anthropic** (`providers/anthropic_llm.py`): extracts `role=="system"` messages into
  the `system` kwarg (joined with `\n\n`), passes the rest as `messages`, defaults
  `max_tokens` to 1024, passes `temperature` via `extra_body` (robust to SDK versions
  whose `messages.stream` signature omits it), streams `stream.text_stream`.
  Same error normalization and `aclose()` as the OpenAI-compatible adapter.

## Factory (`providers/factory.py`)

- `build_llm(LLMConfig, *, timeout=60.0, max_retries=2) -> LLMProvider`,
  `build_embedder(EmbeddingConfig, *, timeout=60.0, max_retries=2) -> EmbeddingProvider`.
  The ingestion worker passes `max_retries=0`: the job owns retry/backoff, and stacking
  SDK retries under it multiplies both wall clock and cost with nobody deciding to.
- `_OPENAI_COMPATIBLE_DEFAULTS` maps `openai_compatible → None`,
  `google → https://generativelanguage.googleapis.com/v1beta/openai/`,
  `mistral → https://api.mistral.ai/v1`. A bot's explicit `base_url` overrides the default.
- Key resolution: if `api_key` present and `api_key_encrypted`, `decrypt()` it (a bad
  token → `ProviderError("provider_config")`); else use the key or the literal
  `"not-needed"` (local servers).
- Unsupported provider, or `build_embedder(provider="anthropic")` (no embedding API):
  `ProviderError("provider_config")`, non-retryable.

## Why Google/Mistral use OpenAI-compat (spec §7 deviation)

The spec listed dedicated adapters for Google and Mistral. Both ship first-party
OpenAI-compatible endpoints, so routing them through the existing adapter gives the same
capability for ~40 lines of factory glue and no new SDKs. The Protocol seam means a
native adapter can replace the compat path later without touching callers. Trade-off:
Gemini's compat layer is beta and unverified against a live call — a manual smoke test is
recommended before declaring Google/Mistral production-ready (see [operations](operations.md)).

## Carry-forward (before Phase 4 / GA)

- **Close clients:** adapters expose `aclose()`, but nothing calls it yet — wire it into
  the app lifespan and the worker shutdown when those exist (tasks 5–6).
- **Batch `embed`** for large documents (provider input caps) — do it in the ingestion
  worker (Phase 3b) or the embedder.
- **Pin bounds:** `openai` is pinned `>=1.40,<4`; `anthropic` is `>=0.40` (unbounded — add
  a ceiling for parity).

## Installed SDK note

This environment's package index resolved unusually high versions (`openai 3.8.0`,
`anthropic 1.4.0`). The adapters use only stable high-level surface, verified present.
Tests use fakes, so they are independent of SDK internals.
