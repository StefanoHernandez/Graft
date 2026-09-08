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
        """Raise ProviderConnectionError if the provider is unreachable/unauthorized."""
        ...
