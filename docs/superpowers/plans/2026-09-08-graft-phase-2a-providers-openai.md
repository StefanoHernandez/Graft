# Graft — Phase 2a: Provider Abstraction + OpenAI-Compatible Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the pluggable LLM/embeddings provider abstraction and its first adapter — OpenAI-compatible — which covers OpenAI, Ollama, and LM Studio via a configurable `base_url`, plus a factory that builds providers from a (per-bot) config with a decrypted API key.

**Architecture:** A `graft.providers` package defines two Protocols — `LLMProvider` (streaming chat) and `EmbeddingProvider` — plus typed config models and errors. The OpenAI-compatible adapter wraps the official async `openai` SDK; adapters take an **injected client** so unit tests exercise our translation logic with a fake client (no network, no HTTP mocking). A factory maps a config dict to the right adapter, decrypting the API key via `graft.security.crypto`, and rejects Anthropic-as-embeddings (spec §7). Anthropic/Google/Mistral adapters are Phase 2b.

**Tech Stack:** Python 3.12, `openai` async SDK (AsyncOpenAI), pydantic v2, pytest + pytest-asyncio. Reuses Phase 1's `graft.security.crypto` and `graft.config`.

**Spec:** `docs/superpowers/specs/2026-09-08-graft-design.md` (§7 Provider abstraction)

## Global Constraints

- **Python** `>=3.12`; dep manager `uv`; commands `uv run <cmd>` from `server/`.
- **Provider names** (string identifiers): `openai_compatible`, `anthropic`, `google`, `mistral`. Only `openai_compatible` is implemented in Phase 2a; the others are recognized by the factory only enough to raise a clear "unsupported (Phase 2b)" / Anthropic-embeddings error.
- **`openai_compatible` covers OpenAI + Ollama + LM Studio** — the only difference is `base_url` (and API key). No separate adapters for Ollama/LM Studio.
- **Dependency injection:** adapters receive an already-constructed `AsyncOpenAI` client via their constructor. The factory builds the real client; unit tests inject a fake. Adapters make **no** network calls at construction.
- **API keys** are stored encrypted; the factory decrypts via `graft.security.crypto.decrypt`. Local servers (Ollama/LM Studio) may have no key → the factory substitutes the literal `"not-needed"`.
- **Streaming contract:** `LLMProvider.stream_chat(...)` is an async generator yielding non-empty content strings only (skip `None`/empty deltas and chunks with no choices).
- Every new Python file must pass `uv run ruff check .` clean; test output must be pristine (0 warnings). Run `uv run ruff check --fix .` before committing.
- Tests live flat under `server/tests/` (existing convention).

---

### Task 1: Provider base interfaces, config models, errors

**Files:**
- Create: `server/graft/providers/__init__.py`
- Create: `server/graft/providers/base.py`
- Create: `server/graft/providers/config.py`
- Modify: `server/pyproject.toml` (add `openai` dependency)
- Test: `server/tests/test_providers_base.py`

**Interfaces:**
- Consumes: nothing from Phase 2 (first task); reuses Phase 1 only indirectly.
- Produces (importable from `graft.providers`):
  - `ChatMessage` — `TypedDict` with `role: str`, `content: str`.
  - `LLMProvider` — `@runtime_checkable` Protocol: `def stream_chat(self, messages: Sequence[ChatMessage], *, model: str, temperature: float = 0.0, max_tokens: int | None = None) -> AsyncIterator[str]` and `async def test_connection(self) -> None`.
  - `EmbeddingProvider` — `@runtime_checkable` Protocol: `async def embed(self, texts: Sequence[str], *, model: str) -> list[list[float]]` and `async def test_connection(self) -> None`.
  - `ProviderError(Exception)`, `ProviderConnectionError(ProviderError)`.
  - `LLMConfig` and `EmbeddingConfig` (pydantic `BaseModel`): fields `provider: str`, `model: str`, `base_url: str | None = None`, `api_key: str | None = None`, `api_key_encrypted: bool = True`.

- [ ] **Step 1: Add the `openai` dependency to `server/pyproject.toml`**

In the `[project]` `dependencies` list, add the line (keep the list alphabetically near the other SDK-ish deps; exact position not important):

```toml
    "openai>=1.40",
```

- [ ] **Step 2: Write the failing test** — `server/tests/test_providers_base.py`

```python
import pytest
from pydantic import ValidationError

from graft.providers import (
    EmbeddingConfig,
    EmbeddingProvider,
    LLMConfig,
    LLMProvider,
    ProviderConnectionError,
    ProviderError,
)


def test_errors_hierarchy():
    assert issubclass(ProviderConnectionError, ProviderError)


def test_llm_config_defaults():
    cfg = LLMConfig(provider="openai_compatible", model="gpt-4o-mini")
    assert cfg.base_url is None
    assert cfg.api_key is None
    assert cfg.api_key_encrypted is True


def test_embedding_config_requires_provider_and_model():
    with pytest.raises(ValidationError):
        EmbeddingConfig(provider="openai_compatible")  # missing model


def test_protocols_are_runtime_checkable():
    class Dummy:
        def stream_chat(self, messages, *, model, temperature=0.0, max_tokens=None): ...
        async def embed(self, texts, *, model): ...
        async def test_connection(self): ...

    d = Dummy()
    assert isinstance(d, LLMProvider)
    assert isinstance(d, EmbeddingProvider)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd server && uv run pytest tests/test_providers_base.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'graft.providers'`.

- [ ] **Step 4: Implement `server/graft/providers/base.py`**

```python
from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Protocol, TypedDict, runtime_checkable


class ChatMessage(TypedDict):
    role: str  # "system" | "user" | "assistant"
    content: str


class ProviderError(Exception):
    """Base error for provider adapters."""


class ProviderConnectionError(ProviderError):
    """Raised when a provider connectivity/auth check fails."""


@runtime_checkable
class LLMProvider(Protocol):
    def stream_chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        """Yield assistant content deltas as they stream in."""
        ...

    async def test_connection(self) -> None:
        """Raise ProviderConnectionError if the provider is unreachable/unauthorized."""
        ...


@runtime_checkable
class EmbeddingProvider(Protocol):
    async def embed(self, texts: Sequence[str], *, model: str) -> list[list[float]]:
        """Return one embedding vector per input text, in order."""
        ...

    async def test_connection(self) -> None:
        ...
```

- [ ] **Step 5: Implement `server/graft/providers/config.py`**

```python
from pydantic import BaseModel


class LLMConfig(BaseModel):
    provider: str
    model: str
    base_url: str | None = None
    api_key: str | None = None
    api_key_encrypted: bool = True


class EmbeddingConfig(BaseModel):
    provider: str
    model: str
    base_url: str | None = None
    api_key: str | None = None
    api_key_encrypted: bool = True
```

- [ ] **Step 6: Implement `server/graft/providers/__init__.py`**

```python
from .base import (
    ChatMessage,
    EmbeddingProvider,
    LLMProvider,
    ProviderConnectionError,
    ProviderError,
)
from .config import EmbeddingConfig, LLMConfig

__all__ = [
    "ChatMessage",
    "EmbeddingProvider",
    "LLMProvider",
    "ProviderConnectionError",
    "ProviderError",
    "EmbeddingConfig",
    "LLMConfig",
]
```

- [ ] **Step 7: Lint, then run the test to verify it passes**

Run: `cd server && uv run ruff check --fix . && uv run ruff check . && uv run pytest tests/test_providers_base.py -v`
Expected: ruff "All checks passed!"; the 4 tests PASS.

- [ ] **Step 8: Commit**

```bash
git add server/graft/providers/ server/tests/test_providers_base.py server/pyproject.toml server/uv.lock
git commit -m "feat(server): provider abstraction base (protocols, config, errors)"
```
End the commit message body with:
Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

---

### Task 2: OpenAI-compatible adapter (chat streaming + embeddings)

**Files:**
- Create: `server/graft/providers/openai_compatible.py`
- Test: `server/tests/test_providers_openai.py`

**Interfaces:**
- Consumes: `graft.providers.base.ChatMessage`, `ProviderConnectionError`.
- Produces:
  - `OpenAICompatibleLLM(client)` — `client` is an `AsyncOpenAI` (or any object exposing `chat.completions.create`, `models.list`). Implements `stream_chat` (async generator yielding content strings) and `async test_connection`.
  - `OpenAICompatibleEmbedder(client)` — implements `async embed(...) -> list[list[float]]` and `async test_connection`.

- [ ] **Step 1: Write the failing test** — `server/tests/test_providers_openai.py`

```python
from types import SimpleNamespace

import pytest

from graft.providers.base import ProviderConnectionError
from graft.providers.openai_compatible import (
    OpenAICompatibleEmbedder,
    OpenAICompatibleLLM,
)


def _chunk(content):
    # Mimics openai ChatCompletionChunk: choices[0].delta.content
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=content))])


class _FakeCompletions:
    def __init__(self, chunks):
        self._chunks = chunks
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)

        async def _gen():
            for c in self._chunks:
                yield c

        return _gen()


class _FakeEmbeddings:
    def __init__(self, vectors):
        self._vectors = vectors
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(data=[SimpleNamespace(embedding=v) for v in self._vectors])


class _FakeModels:
    def __init__(self, error=None):
        self._error = error

    async def list(self):
        if self._error:
            raise self._error
        return SimpleNamespace(data=[])


def _fake_client(chunks=None, vectors=None, models_error=None):
    return SimpleNamespace(
        chat=SimpleNamespace(completions=_FakeCompletions(chunks or [])),
        embeddings=_FakeEmbeddings(vectors or []),
        models=_FakeModels(models_error),
    )


async def test_stream_chat_yields_only_nonempty_content():
    client = _fake_client(chunks=[_chunk("Hello"), _chunk(None), _chunk(""), _chunk(" world")])
    llm = OpenAICompatibleLLM(client)
    out = [tok async for tok in llm.stream_chat(
        [{"role": "user", "content": "hi"}], model="m", max_tokens=64)]
    assert out == ["Hello", " world"]
    # max_tokens forwarded, stream requested
    sent = client.chat.completions.calls[0]
    assert sent["stream"] is True
    assert sent["model"] == "m"
    assert sent["max_tokens"] == 64


async def test_stream_chat_omits_max_tokens_when_none():
    client = _fake_client(chunks=[_chunk("a")])
    llm = OpenAICompatibleLLM(client)
    _ = [tok async for tok in llm.stream_chat([{"role": "user", "content": "x"}], model="m")]
    assert "max_tokens" not in client.chat.completions.calls[0]


async def test_embed_returns_vectors_in_order():
    client = _fake_client(vectors=[[0.1, 0.2], [0.3, 0.4]])
    emb = OpenAICompatibleEmbedder(client)
    result = await emb.embed(["a", "b"], model="e")
    assert result == [[0.1, 0.2], [0.3, 0.4]]
    assert client.embeddings.calls[0]["input"] == ["a", "b"]


async def test_test_connection_ok():
    llm = OpenAICompatibleLLM(_fake_client())
    await llm.test_connection()  # no raise


async def test_test_connection_wraps_errors():
    client = _fake_client(models_error=RuntimeError("boom"))
    llm = OpenAICompatibleLLM(client)
    with pytest.raises(ProviderConnectionError):
        await llm.test_connection()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd server && uv run pytest tests/test_providers_openai.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'graft.providers.openai_compatible'`.

- [ ] **Step 3: Implement `server/graft/providers/openai_compatible.py`**

```python
from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

from openai import AsyncOpenAI

from .base import ChatMessage, ProviderConnectionError


class OpenAICompatibleLLM:
    """LLM adapter for any OpenAI-compatible API (OpenAI, Ollama, LM Studio)."""

    def __init__(self, client: AsyncOpenAI):
        self._client = client

    async def stream_chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        kwargs: dict = {
            "model": model,
            "messages": list(messages),
            "stream": True,
            "temperature": temperature,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        stream = await self._client.chat.completions.create(**kwargs)
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta

    async def test_connection(self) -> None:
        try:
            await self._client.models.list()
        except Exception as exc:  # noqa: BLE001 - normalize any client/transport error
            raise ProviderConnectionError(str(exc)) from exc


class OpenAICompatibleEmbedder:
    """Embedding adapter for any OpenAI-compatible API."""

    def __init__(self, client: AsyncOpenAI):
        self._client = client

    async def embed(self, texts: Sequence[str], *, model: str) -> list[list[float]]:
        resp = await self._client.embeddings.create(model=model, input=list(texts))
        return [item.embedding for item in resp.data]

    async def test_connection(self) -> None:
        try:
            await self._client.models.list()
        except Exception as exc:  # noqa: BLE001 - normalize any client/transport error
            raise ProviderConnectionError(str(exc)) from exc
```

- [ ] **Step 4: Lint, then run the test to verify it passes**

Run: `cd server && uv run ruff check --fix . && uv run ruff check . && uv run pytest tests/test_providers_openai.py -v`
Expected: ruff clean; all 5 tests PASS, pristine.

> Note on the `# noqa: BLE001`: ruff's default rule set does not enable `BLE` (blind-except), so this comment is inert today but documents intent and is future-proof. `ruff check` will not complain about an unused noqa under the default config. If `ruff check` reports `RUF100` (unused noqa) in this project, remove the two `# noqa: BLE001` comments and re-run — the broad `except Exception` is intentional and allowed under the default rule set.

- [ ] **Step 5: Commit**

```bash
git add server/graft/providers/openai_compatible.py server/tests/test_providers_openai.py
git commit -m "feat(server): OpenAI-compatible LLM + embedding adapter"
```
End the commit message body with:
Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

---

### Task 3: Provider factory (build from config, decrypt key, validation)

**Files:**
- Create: `server/graft/providers/factory.py`
- Modify: `server/graft/providers/__init__.py` (export `build_llm`, `build_embedder`)
- Test: `server/tests/test_providers_factory.py`

**Interfaces:**
- Consumes: `graft.providers.config.LLMConfig`/`EmbeddingConfig`, `graft.providers.base.{LLMProvider,EmbeddingProvider,ProviderError}`, `graft.providers.openai_compatible.{OpenAICompatibleLLM,OpenAICompatibleEmbedder}`, `graft.security.crypto.decrypt`.
- Produces:
  - `build_llm(config: LLMConfig) -> LLMProvider`
  - `build_embedder(config: EmbeddingConfig) -> EmbeddingProvider`
  - Both build an `AsyncOpenAI` client (for `openai_compatible`) with the resolved key + `base_url`. Unknown providers raise `ProviderError`; `build_embedder` with `provider="anthropic"` raises `ProviderError` explaining Anthropic has no embeddings API.

- [ ] **Step 1: Write the failing test** — `server/tests/test_providers_factory.py`

```python
import os

import pytest
from cryptography.fernet import Fernet


@pytest.fixture(autouse=True)
def _encryption_key():
    os.environ["ENCRYPTION_KEY"] = Fernet.generate_key().decode()
    from graft.config import get_settings

    get_settings.cache_clear()
    yield


def test_build_llm_openai_compatible_decrypts_key():
    from graft.providers.config import LLMConfig
    from graft.providers.factory import build_llm
    from graft.providers.openai_compatible import OpenAICompatibleLLM
    from graft.security import crypto

    cfg = LLMConfig(
        provider="openai_compatible",
        model="gpt-4o-mini",
        base_url="http://example.test/v1",
        api_key=crypto.encrypt("sk-real-secret"),
        api_key_encrypted=True,
    )
    provider = build_llm(cfg)
    assert isinstance(provider, OpenAICompatibleLLM)
    # The wrapped AsyncOpenAI client received the decrypted key + base_url.
    assert provider._client.api_key == "sk-real-secret"
    assert "example.test/v1" in str(provider._client.base_url)


def test_build_llm_local_without_key_uses_placeholder():
    from graft.providers.config import LLMConfig
    from graft.providers.factory import build_llm

    cfg = LLMConfig(
        provider="openai_compatible",
        model="llama3",
        base_url="http://localhost:11434/v1",
        api_key=None,
        api_key_encrypted=False,
    )
    provider = build_llm(cfg)
    assert provider._client.api_key == "not-needed"


def test_build_llm_unknown_provider_raises():
    from graft.providers.base import ProviderError
    from graft.providers.config import LLMConfig
    from graft.providers.factory import build_llm

    with pytest.raises(ProviderError):
        build_llm(LLMConfig(provider="does-not-exist", model="m"))


def test_build_embedder_openai_compatible():
    from graft.providers.config import EmbeddingConfig
    from graft.providers.factory import build_embedder
    from graft.providers.openai_compatible import OpenAICompatibleEmbedder

    cfg = EmbeddingConfig(
        provider="openai_compatible", model="text-embedding-3-small",
        api_key=None, api_key_encrypted=False,
    )
    assert isinstance(build_embedder(cfg), OpenAICompatibleEmbedder)


def test_build_embedder_anthropic_rejected():
    from graft.providers.base import ProviderError
    from graft.providers.config import EmbeddingConfig
    from graft.providers.factory import build_embedder

    with pytest.raises(ProviderError, match="embedding"):
        build_embedder(EmbeddingConfig(provider="anthropic", model="whatever"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd server && uv run pytest tests/test_providers_factory.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'graft.providers.factory'`.

- [ ] **Step 3: Implement `server/graft/providers/factory.py`**

```python
from __future__ import annotations

from openai import AsyncOpenAI

from ..security.crypto import decrypt
from .base import EmbeddingProvider, LLMProvider, ProviderError
from .config import EmbeddingConfig, LLMConfig
from .openai_compatible import OpenAICompatibleEmbedder, OpenAICompatibleLLM


def _resolve_key(api_key: str | None, encrypted: bool) -> str:
    if api_key and encrypted:
        return decrypt(api_key)
    return api_key or "not-needed"


def _openai_client(config: LLMConfig | EmbeddingConfig) -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=_resolve_key(config.api_key, config.api_key_encrypted),
        base_url=config.base_url,
    )


def build_llm(config: LLMConfig) -> LLMProvider:
    if config.provider == "openai_compatible":
        return OpenAICompatibleLLM(_openai_client(config))
    raise ProviderError(f"Unsupported LLM provider: {config.provider!r} (Phase 2b adds it)")


def build_embedder(config: EmbeddingConfig) -> EmbeddingProvider:
    if config.provider == "openai_compatible":
        return OpenAICompatibleEmbedder(_openai_client(config))
    if config.provider == "anthropic":
        raise ProviderError(
            "Anthropic has no embedding API; configure a separate embedding provider"
        )
    raise ProviderError(
        f"Unsupported embedding provider: {config.provider!r} (Phase 2b adds it)"
    )
```

- [ ] **Step 4: Export the factory from `server/graft/providers/__init__.py`**

Add `build_llm`, `build_embedder` to the imports and `__all__`. The file becomes:

```python
from .base import (
    ChatMessage,
    EmbeddingProvider,
    LLMProvider,
    ProviderConnectionError,
    ProviderError,
)
from .config import EmbeddingConfig, LLMConfig
from .factory import build_embedder, build_llm

__all__ = [
    "ChatMessage",
    "EmbeddingProvider",
    "LLMProvider",
    "ProviderConnectionError",
    "ProviderError",
    "EmbeddingConfig",
    "LLMConfig",
    "build_embedder",
    "build_llm",
]
```

- [ ] **Step 5: Lint, then run the full suite to verify it passes**

Run: `cd server && uv run ruff check --fix . && uv run ruff check . && uv run pytest -v`
Expected: ruff clean; ALL tests pass (Phase 1 tests + the three provider test files), pristine.

- [ ] **Step 6: Commit**

```bash
git add server/graft/providers/factory.py server/graft/providers/__init__.py server/tests/test_providers_factory.py
git commit -m "feat(server): provider factory with key decryption and validation"
```
End the commit message body with:
Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

---

## Phase 2a Definition of Done

- `cd server && uv run pytest -v` → all green (Phase 1 suite + `test_providers_base`, `test_providers_openai`, `test_providers_factory`), pristine.
- `uv run ruff check .` → clean.
- `graft.providers` exposes `LLMProvider`/`EmbeddingProvider` Protocols, `LLMConfig`/`EmbeddingConfig`, `ProviderError`/`ProviderConnectionError`, `build_llm`/`build_embedder`.
- OpenAI-compatible adapter streams chat content deltas and returns embedding vectors; `test_connection` normalizes failures to `ProviderConnectionError`.
- Factory decrypts encrypted keys, substitutes `"not-needed"` for keyless local servers, and rejects unknown providers + Anthropic-as-embeddings.

## What Phase 2a deliberately excludes (Phase 2b)

- Anthropic (chat), Google/Gemini (chat + embeddings), Mistral (chat + embeddings) adapters — same Protocols, added as sibling adapter modules + factory branches, each with its own DI-based tests.
- Wiring providers into an HTTP endpoint (chat / connection-test) — that is Phase 4 (RAG + Chat API) and Phase 6 (Admin API).
