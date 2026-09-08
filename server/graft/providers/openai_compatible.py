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
        except Exception as exc:
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
        except Exception as exc:
            raise ProviderConnectionError(str(exc)) from exc
