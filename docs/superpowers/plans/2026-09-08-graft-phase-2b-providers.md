# Graft — Phase 2b: Anthropic, Google & Mistral Providers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete provider coverage — add a native **Anthropic** chat adapter, and wire **Google/Gemini** and **Mistral** through the existing OpenAI-compatible adapter (both expose OpenAI-compatible endpoints), so all six backends (OpenAI, Ollama, LM Studio, Mistral, Google, Anthropic) are reachable via the factory.

**Architecture:** Anthropic has no OpenAI-compatible endpoint and no embeddings API, so it gets a dedicated `AnthropicLLM` adapter over the async `anthropic` SDK (same `LLMProvider` Protocol, dependency-injected client). Mistral and Gemini both offer OpenAI-compatible REST endpoints, so the factory routes them to the **existing** `OpenAICompatibleLLM`/`OpenAICompatibleEmbedder` with a provider-default `base_url` — no new SDK, no new adapter. The factory gains `anthropic`/`google`/`mistral` branches, wraps key-decryption failures in `ProviderError`, and keeps rejecting Anthropic-as-embeddings.

> **Deviation from spec §7 (documented):** the spec listed "dedicated Anthropic, Google, Mistral" adapters. Mistral and Gemini are instead served through their OpenAI-compatible endpoints via the existing adapter — same user-facing capability, far less code and risk. The `LLMProvider`/`EmbeddingProvider` Protocols let a native Google/Mistral adapter replace the compat path later without touching callers, if a compat gap ever appears.

**Tech Stack:** Python 3.12, `anthropic` async SDK (AsyncAnthropic), reuses `openai` async SDK + `graft.providers.openai_compatible` + `graft.security.crypto`. Tests: pytest + DI fakes (no network).

**Spec:** `docs/superpowers/specs/2026-09-08-graft-design.md` (§7 Provider abstraction)

## Global Constraints

- **Python** `>=3.12`; dep manager `uv`; commands `uv run <cmd>` from `server/`.
- **Provider ids:** `openai_compatible`, `anthropic`, `google`, `mistral`.
- **Anthropic** = native adapter, **chat only** (no embeddings — factory rejects `anthropic` for embeddings). **Google** and **Mistral** = existing `OpenAICompatible*` adapters with provider-default `base_url` (overridable by `config.base_url`).
- **Default base URLs:** `google` → `https://generativelanguage.googleapis.com/v1beta/openai/`; `mistral` → `https://api.mistral.ai/v1`.
- **Dependency injection:** every adapter takes an already-constructed client; adapters make no network call at construction; unit tests inject fakes (`types.SimpleNamespace` / small fakes) — no network.
- **Anthropic message mapping:** `role == "system"` messages are extracted and joined with `\n\n` into the `system` kwarg; remaining `user`/`assistant` messages pass through as `messages`; `max_tokens` defaults to `1024` when `None` (Anthropic requires it); `temperature` is passed via `extra_body={"temperature": ...}` (robust across SDK versions whose `messages.stream` signature omits a `temperature` kwarg).
- **Key decryption failures** (e.g. wrong/rotated key) must surface as `ProviderError`, not a raw `cryptography.fernet.InvalidToken`.
- Every new Python file passes `uv run ruff check .` clean; test output pristine (0 warnings). Run `uv run ruff check --fix .` before committing.
- Tests live flat under `server/tests/`.

---

### Task 1: Anthropic adapter (native, chat-only)

**Files:**
- Create: `server/graft/providers/anthropic_llm.py`
- Modify: `server/pyproject.toml` (add `anthropic` dependency)
- Test: `server/tests/test_providers_anthropic.py`

**Interfaces:**
- Consumes: `graft.providers.base.ChatMessage`, `graft.providers.base.ProviderConnectionError`.
- Produces: `graft.providers.anthropic_llm.AnthropicLLM(client)` where `client` is an `anthropic.AsyncAnthropic` (or any object exposing `messages.stream(**kwargs)` returning an async context manager with a `text_stream` async iterator, and an awaitable `models.list()`). Implements `stream_chat` (async generator) + `async test_connection`.

- [ ] **Step 1: Add the `anthropic` dependency to `server/pyproject.toml`**

In `[project]` `dependencies`, add:

```toml
    "anthropic>=0.40",
```

- [ ] **Step 2: Write the failing test** — `server/tests/test_providers_anthropic.py`

```python
from types import SimpleNamespace

import pytest

from graft.providers.anthropic_llm import AnthropicLLM
from graft.providers.base import ProviderConnectionError


class _FakeStreamCM:
    def __init__(self, texts):
        self._texts = texts

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    @property
    def text_stream(self):
        async def _gen():
            for t in self._texts:
                yield t

        return _gen()


class _FakeMessages:
    def __init__(self, texts):
        self._texts = texts
        self.calls = []

    def stream(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeStreamCM(self._texts)


class _FakeModels:
    def __init__(self, error=None):
        self._error = error

    async def list(self):
        if self._error:
            raise self._error
        return SimpleNamespace(data=[])


def _fake_client(texts=None, models_error=None):
    return SimpleNamespace(messages=_FakeMessages(texts or []), models=_FakeModels(models_error))


async def test_stream_chat_yields_text_and_skips_empty():
    client = _fake_client(texts=["Hel", "", "lo"])
    llm = AnthropicLLM(client)
    out = [t async for t in llm.stream_chat(
        [{"role": "user", "content": "hi"}], model="claude", max_tokens=32)]
    assert out == ["Hel", "lo"]
    sent = client.messages.calls[0]
    assert sent["model"] == "claude"
    assert sent["max_tokens"] == 32
    assert sent["extra_body"] == {"temperature": 0.0}


async def test_system_messages_are_extracted():
    client = _fake_client(texts=["ok"])
    llm = AnthropicLLM(client)
    _ = [t async for t in llm.stream_chat(
        [
            {"role": "system", "content": "Be terse."},
            {"role": "system", "content": "Cite sources."},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "prev"},
        ],
        model="claude",
        temperature=0.3,
    )]
    sent = client.messages.calls[0]
    assert sent["system"] == "Be terse.\n\nCite sources."
    assert sent["messages"] == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "prev"},
    ]
    assert sent["extra_body"] == {"temperature": 0.3}


async def test_max_tokens_defaults_to_1024():
    client = _fake_client(texts=["x"])
    llm = AnthropicLLM(client)
    _ = [t async for t in llm.stream_chat([{"role": "user", "content": "hi"}], model="claude")]
    assert client.messages.calls[0]["max_tokens"] == 1024


async def test_no_system_key_when_no_system_messages():
    client = _fake_client(texts=["x"])
    llm = AnthropicLLM(client)
    _ = [t async for t in llm.stream_chat([{"role": "user", "content": "hi"}], model="claude")]
    assert "system" not in client.messages.calls[0]


async def test_test_connection_ok_and_error_wrapping():
    await AnthropicLLM(_fake_client()).test_connection()
    with pytest.raises(ProviderConnectionError):
        await AnthropicLLM(_fake_client(models_error=RuntimeError("boom"))).test_connection()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd server && uv run pytest tests/test_providers_anthropic.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'graft.providers.anthropic_llm'`.

- [ ] **Step 4: Implement `server/graft/providers/anthropic_llm.py`**

```python
from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

from anthropic import AsyncAnthropic

from .base import ChatMessage, ProviderConnectionError

_DEFAULT_MAX_TOKENS = 1024


class AnthropicLLM:
    """Chat adapter for Anthropic's Messages API (no embeddings)."""

    def __init__(self, client: AsyncAnthropic):
        self._client = client

    async def stream_chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        convo = [
            {"role": m["role"], "content": m["content"]}
            for m in messages
            if m["role"] != "system"
        ]
        kwargs: dict = {
            "model": model,
            "messages": convo,
            "max_tokens": max_tokens or _DEFAULT_MAX_TOKENS,
            # temperature via extra_body: robust across SDK versions whose
            # messages.stream() signature does not expose a temperature kwarg.
            "extra_body": {"temperature": temperature},
        }
        if system:
            kwargs["system"] = system
        async with self._client.messages.stream(**kwargs) as stream:
            async for text in stream.text_stream:
                if text:
                    yield text

    async def test_connection(self) -> None:
        try:
            await self._client.models.list()
        except Exception as exc:
            raise ProviderConnectionError(str(exc)) from exc
```

- [ ] **Step 5: Lint, then run the test to verify it passes**

Run: `cd server && uv run ruff check --fix . && uv run ruff check . && uv run pytest tests/test_providers_anthropic.py -v`
Expected: ruff clean; all 5 tests PASS. (If ruff flags `RUF100` on any noqa you did not add, ignore — this file has none. If it flags `BLE001` on `except Exception`, that rule is off by default; do not add a noqa.)

- [ ] **Step 6: Commit**

```bash
git add server/graft/providers/anthropic_llm.py server/tests/test_providers_anthropic.py server/pyproject.toml server/uv.lock
git commit -m "feat(server): native Anthropic chat adapter"
```
End the commit message body with:
Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

---

### Task 2: Factory branches for anthropic / google / mistral

**Files:**
- Modify: `server/graft/providers/factory.py`
- Test: `server/tests/test_providers_factory.py` (add cases)

**Interfaces:**
- Consumes: `graft.providers.anthropic_llm.AnthropicLLM`, `graft.providers.openai_compatible.{OpenAICompatibleLLM,OpenAICompatibleEmbedder}`, `anthropic.AsyncAnthropic`, `openai.AsyncOpenAI`, `graft.security.crypto.decrypt`, `cryptography.fernet.InvalidToken`.
- Produces (unchanged signatures): `build_llm(LLMConfig) -> LLMProvider`, `build_embedder(EmbeddingConfig) -> EmbeddingProvider`. New behavior: `anthropic`/`google`/`mistral` are supported; decrypt failures raise `ProviderError`.

- [ ] **Step 1: Write the failing tests** — append to `server/tests/test_providers_factory.py`

```python
def test_build_llm_anthropic():
    from graft.providers.anthropic_llm import AnthropicLLM
    from graft.providers.config import LLMConfig
    from graft.providers.factory import build_llm
    from graft.security import crypto

    cfg = LLMConfig(
        provider="anthropic",
        model="claude-sonnet-5",
        api_key=crypto.encrypt("sk-ant-xyz"),
        api_key_encrypted=True,
    )
    provider = build_llm(cfg)
    assert isinstance(provider, AnthropicLLM)
    assert provider._client.api_key == "sk-ant-xyz"


def test_build_llm_google_uses_default_base_url():
    from graft.providers.config import LLMConfig
    from graft.providers.factory import build_llm
    from graft.providers.openai_compatible import OpenAICompatibleLLM

    provider = build_llm(LLMConfig(
        provider="google", model="gemini-2.5-flash", api_key=None, api_key_encrypted=False))
    assert isinstance(provider, OpenAICompatibleLLM)
    assert "generativelanguage.googleapis.com/v1beta/openai" in str(provider._client.base_url)


def test_build_llm_mistral_uses_default_base_url():
    from graft.providers.config import LLMConfig
    from graft.providers.factory import build_llm
    from graft.providers.openai_compatible import OpenAICompatibleLLM

    provider = build_llm(LLMConfig(
        provider="mistral", model="mistral-large-latest", api_key=None, api_key_encrypted=False))
    assert isinstance(provider, OpenAICompatibleLLM)
    assert "api.mistral.ai/v1" in str(provider._client.base_url)


def test_build_llm_explicit_base_url_overrides_default():
    from graft.providers.config import LLMConfig
    from graft.providers.factory import build_llm

    provider = build_llm(LLMConfig(
        provider="mistral", model="m", base_url="http://proxy.local/v1",
        api_key=None, api_key_encrypted=False))
    assert "proxy.local/v1" in str(provider._client.base_url)


def test_build_embedder_google_and_mistral():
    from graft.providers.config import EmbeddingConfig
    from graft.providers.factory import build_embedder
    from graft.providers.openai_compatible import OpenAICompatibleEmbedder

    g = build_embedder(EmbeddingConfig(
        provider="google", model="text-embedding-004", api_key=None, api_key_encrypted=False))
    m = build_embedder(EmbeddingConfig(
        provider="mistral", model="mistral-embed", api_key=None, api_key_encrypted=False))
    assert isinstance(g, OpenAICompatibleEmbedder)
    assert isinstance(m, OpenAICompatibleEmbedder)
    assert "generativelanguage.googleapis.com/v1beta/openai" in str(g._client.base_url)
    assert "api.mistral.ai/v1" in str(m._client.base_url)


def test_decrypt_failure_raises_provider_error():
    from graft.providers.base import ProviderError
    from graft.providers.config import LLMConfig
    from graft.providers.factory import build_llm

    # A syntactically invalid Fernet token -> decrypt fails -> ProviderError (not InvalidToken).
    with pytest.raises(ProviderError):
        build_llm(LLMConfig(
            provider="openai_compatible", model="m",
            api_key="not-a-valid-fernet-token", api_key_encrypted=True))
```

> These tests rely on the existing autouse `_encryption_key` fixture already in `test_providers_factory.py` (sets `ENCRYPTION_KEY` + clears the settings cache). Do not duplicate it.

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `cd server && uv run pytest tests/test_providers_factory.py -v`
Expected: the new cases FAIL (anthropic/google/mistral currently raise `ProviderError` "unsupported"; decrypt-failure currently raises `InvalidToken`, not `ProviderError`).

- [ ] **Step 3: Rewrite `server/graft/providers/factory.py`**

```python
from __future__ import annotations

from anthropic import AsyncAnthropic
from cryptography.fernet import InvalidToken
from openai import AsyncOpenAI

from ..security.crypto import decrypt
from .anthropic_llm import AnthropicLLM
from .base import EmbeddingProvider, LLMProvider, ProviderError
from .config import EmbeddingConfig, LLMConfig
from .openai_compatible import OpenAICompatibleEmbedder, OpenAICompatibleLLM

# Providers reachable through an OpenAI-compatible endpoint, with their default base URLs.
_OPENAI_COMPATIBLE_DEFAULTS = {
    "openai_compatible": None,  # OpenAI (or an admin-provided base_url for Ollama/LM Studio)
    "google": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "mistral": "https://api.mistral.ai/v1",
}


def _resolve_key(api_key: str | None, encrypted: bool) -> str:
    if api_key and encrypted:
        try:
            return decrypt(api_key)
        except InvalidToken as exc:
            raise ProviderError("Could not decrypt provider API key") from exc
    return api_key or "not-needed"


def _openai_client(config: LLMConfig | EmbeddingConfig, default_base_url: str | None) -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=_resolve_key(config.api_key, config.api_key_encrypted),
        base_url=config.base_url or default_base_url,
    )


def _anthropic_client(config: LLMConfig) -> AsyncAnthropic:
    return AsyncAnthropic(
        api_key=_resolve_key(config.api_key, config.api_key_encrypted),
        base_url=config.base_url or None,
    )


def build_llm(config: LLMConfig) -> LLMProvider:
    if config.provider == "anthropic":
        return AnthropicLLM(_anthropic_client(config))
    if config.provider in _OPENAI_COMPATIBLE_DEFAULTS:
        return OpenAICompatibleLLM(_openai_client(config, _OPENAI_COMPATIBLE_DEFAULTS[config.provider]))
    raise ProviderError(f"Unsupported LLM provider: {config.provider!r}")


def build_embedder(config: EmbeddingConfig) -> EmbeddingProvider:
    if config.provider == "anthropic":
        raise ProviderError(
            "Anthropic has no embedding API; configure a separate embedding provider"
        )
    if config.provider in _OPENAI_COMPATIBLE_DEFAULTS:
        return OpenAICompatibleEmbedder(
            _openai_client(config, _OPENAI_COMPATIBLE_DEFAULTS[config.provider])
        )
    raise ProviderError(f"Unsupported embedding provider: {config.provider!r}")
```

- [ ] **Step 4: Lint, then run the full suite to verify it passes**

Run: `cd server && uv run ruff check --fix . && uv run ruff check . && uv run pytest -v`
Expected: ruff clean; ALL tests pass (every prior test + the 6 new factory cases), pristine. The existing `test_build_llm_unknown_provider_raises` and `test_build_embedder_anthropic_rejected` still pass unchanged.

- [ ] **Step 5: Commit**

```bash
git add server/graft/providers/factory.py server/tests/test_providers_factory.py
git commit -m "feat(server): factory support for anthropic, google, mistral providers"
```
End the commit message body with:
Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

---

### Task 3: OpenAI-adapter hardening (carry-forward from Phase 2a review)

**Files:**
- Modify: `server/graft/providers/openai_compatible.py`
- Modify: `server/graft/providers/config.py`
- Modify: `server/graft/providers/base.py`
- Modify: `server/pyproject.toml` (bound the `openai` pin)
- Test: `server/tests/test_providers_openai.py` (add one case)

**Interfaces:**
- Consumes/Produces: no signature changes. `OpenAICompatibleEmbedder.embed` becomes order-robust; `stream_chat` gains a covering test for the choiceless-chunk branch.

- [ ] **Step 1: Write the failing test** — append to `server/tests/test_providers_openai.py`

```python
async def test_stream_chat_skips_chunks_without_choices():
    # A usage-only / content-filter chunk with choices=[] must be skipped, not crash.
    client = _fake_client(chunks=[
        SimpleNamespace(choices=[]),
        _chunk("hi"),
        SimpleNamespace(choices=[]),
    ])
    llm = OpenAICompatibleLLM(client)
    out = [tok async for tok in llm.stream_chat([{"role": "user", "content": "x"}], model="m")]
    assert out == ["hi"]


async def test_embed_returns_index_ordered_vectors():
    # Even if the server returns data out of order, embed() must sort by index.
    client = SimpleNamespace(
        embeddings=_FakeEmbeddingsIndexed([
            SimpleNamespace(index=1, embedding=[9.0]),
            SimpleNamespace(index=0, embedding=[8.0]),
        ]),
    )
    emb = OpenAICompatibleEmbedder(client)
    assert await emb.embed(["a", "b"], model="e") == [[8.0], [9.0]]
```

Also add this fake near the other fakes in the file:

```python
class _FakeEmbeddingsIndexed:
    def __init__(self, data):
        self._data = data
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(data=self._data)
```

- [ ] **Step 2: Run to verify the new cases fail**

Run: `cd server && uv run pytest tests/test_providers_openai.py -v`
Expected: `test_stream_chat_skips_chunks_without_choices` PASSES already (the guard exists); `test_embed_returns_index_ordered_vectors` FAILS (current `embed` preserves response order, does not sort by `index`).

- [ ] **Step 3: Make `embed` order-robust** in `server/graft/providers/openai_compatible.py`

Replace the `embed` method body with:

```python
    async def embed(self, texts: Sequence[str], *, model: str) -> list[list[float]]:
        resp = await self._client.embeddings.create(model=model, input=list(texts))
        ordered = sorted(resp.data, key=lambda item: getattr(item, "index", 0))
        return [item.embedding for item in ordered]
```

- [ ] **Step 4: Consistency polish**

In `server/graft/providers/config.py`, add as the first line:

```python
from __future__ import annotations
```

In `server/graft/providers/base.py`, give `EmbeddingProvider.test_connection` the same docstring shape as `LLMProvider.test_connection`:

```python
    async def test_connection(self) -> None:
        """Raise ProviderConnectionError if the provider is unreachable/unauthorized."""
        ...
```

In `server/pyproject.toml`, bound the openai pin (change the existing line):

```toml
    "openai>=1.40,<4",
```

- [ ] **Step 5: Lint, then run the full suite**

Run: `cd server && uv run ruff check --fix . && uv run ruff check . && uv run pytest -v`
Expected: ruff clean; ALL tests pass, pristine. (`uv.lock` should be unchanged since the installed `openai` 3.8.0 already satisfies `>=1.40,<4` — if `uv` rewrites the lock, include it in the commit.)

- [ ] **Step 6: Commit**

```bash
git add server/graft/providers/openai_compatible.py server/graft/providers/config.py server/graft/providers/base.py server/pyproject.toml server/tests/test_providers_openai.py
git commit -m "refactor(server): harden OpenAI adapter (order-robust embed, choiceless-chunk test, pin bound)"
```
End the commit message body with:
Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

---

## Phase 2b Definition of Done

- `cd server && uv run pytest -v` → all green (all prior tests + `test_providers_anthropic` + new factory + new openai cases), pristine.
- `uv run ruff check .` → clean.
- `build_llm` builds providers for `openai_compatible`, `anthropic`, `google`, `mistral`; `build_embedder` for `openai_compatible`, `google`, `mistral` and rejects `anthropic`.
- Anthropic adapter extracts system messages, defaults `max_tokens`, passes temperature via `extra_body`, streams text, normalizes connection errors.
- Google & Mistral resolve to the OpenAI-compatible adapter with their default base URLs (overridable).
- Decrypt failures raise `ProviderError`.

## What Phase 2b deliberately excludes

- A native Google/Mistral adapter (only needed if their OpenAI-compat endpoints prove insufficient — swap behind the same Protocol then).
- Mid-stream error normalization for `stream_chat`/`embed` into `ProviderConnectionError` (only `test_connection` normalizes today) — revisit if Phase 4's chat endpoint needs uniform provider-agnostic error handling.
- A real-network integration/smoke test against live providers (needs credentials; out of scope for unit-tested Phase 2).
- Wiring providers into any HTTP endpoint — Phase 4 (Chat API) and Phase 6 (Admin API).
