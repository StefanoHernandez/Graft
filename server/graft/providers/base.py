from __future__ import annotations

import math
from collections.abc import AsyncIterator, Sequence
from typing import Protocol, TypedDict, runtime_checkable


class ChatMessage(TypedDict):
    role: str  # "system" | "user" | "assistant"
    content: str


class ProviderError(Exception):
    """A provider failure, reduced to a stable public code.

    ``str(exc)`` is the code and nothing else: provider SDK messages can embed
    the API key or the request body, so they never reach an admin, a visitor,
    or a log line. ``retryable`` says whether a worker may try the same call
    again; permanent failures (auth, config) must not burn attempts or budget.
    """

    def __init__(self, code: str, *, retryable: bool = False):
        self.code = code
        self.retryable = retryable
        super().__init__(code)


class ProviderConnectionError(ProviderError):
    """Raised when a provider connectivity/auth check fails."""


PROVIDER_AUTH = "provider_auth"
PROVIDER_RATE_LIMIT = "provider_rate_limit"
PROVIDER_TIMEOUT = "provider_timeout"
PROVIDER_UNAVAILABLE = "provider_unavailable"
PROVIDER_INVALID_RESPONSE = "provider_invalid_response"
PROVIDER_CONFIG = "provider_config"

_RETRYABLE = {PROVIDER_RATE_LIMIT, PROVIDER_TIMEOUT, PROVIDER_UNAVAILABLE}

# Codes keyed by HTTP status. 400/404/422-style answers mean the request itself is
# wrong (bad model name, wrong endpoint): retrying cannot fix them.
_BY_STATUS = {
    400: PROVIDER_CONFIG,
    401: PROVIDER_AUTH,
    403: PROVIDER_AUTH,
    404: PROVIDER_CONFIG,
    408: PROVIDER_TIMEOUT,
    429: PROVIDER_RATE_LIMIT,
}


def _classify(exc: BaseException) -> tuple[str, bool]:
    name = type(exc).__name__
    # Matched by name so one mapping serves both the openai and anthropic SDKs,
    # whose exception classes share these names but no common base.
    if "Timeout" in name:
        return PROVIDER_TIMEOUT, True
    if "RateLimit" in name:
        return PROVIDER_RATE_LIMIT, True
    if "Authentication" in name or "PermissionDenied" in name:
        return PROVIDER_AUTH, False
    if "APIConnection" in name:
        return PROVIDER_UNAVAILABLE, True

    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        if status in _BY_STATUS:
            code = _BY_STATUS[status]
            return code, code in _RETRYABLE
        if status >= 500:
            return PROVIDER_UNAVAILABLE, True
        return PROVIDER_INVALID_RESPONSE, False

    if isinstance(exc, TimeoutError):
        return PROVIDER_TIMEOUT, True
    # Unknown failure: surface it as unavailable but do NOT retry — we cannot tell
    # a transient blip from a bug, and a blind retry doubles the provider bill.
    return PROVIDER_UNAVAILABLE, False


def provider_error(exc: BaseException, *, connection: bool = False) -> ProviderError:
    """Normalize any provider/SDK exception into a coded ProviderError."""
    if isinstance(exc, ProviderError):
        return exc
    code, retryable = _classify(exc)
    cls = ProviderConnectionError if connection else ProviderError
    return cls(code, retryable=retryable)


def validate_vectors(vectors: list[list[float]], *, expected: int) -> None:
    """Reject embedding batches a caller must not store.

    A short batch silently misaligns chunks and vectors; a zero or non-finite
    vector poisons every later ``<=>`` comparison.
    """
    if len(vectors) != expected:
        raise ProviderError(PROVIDER_INVALID_RESPONSE)
    if not vectors:
        return
    dim = len(vectors[0])
    if dim == 0:
        raise ProviderError(PROVIDER_INVALID_RESPONSE)
    for vector in vectors:
        if len(vector) != dim:
            raise ProviderError(PROVIDER_INVALID_RESPONSE)
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in vector):
            raise ProviderError(PROVIDER_INVALID_RESPONSE)
        if not any(vector):
            raise ProviderError(PROVIDER_INVALID_RESPONSE)


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
        """Raise ProviderConnectionError if the provider is unreachable/unauthorized."""
        ...
