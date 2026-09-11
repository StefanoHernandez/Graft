from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

from openai import AsyncOpenAI

from .base import ChatMessage, provider_error, validate_vectors


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
        # The try spans the whole stream: a provider can fail on the first call or
        # halfway through the tokens. CancelledError/GeneratorExit are BaseException,
        # so a disconnected visitor still cancels instead of looking like an outage.
        try:
            stream = await self._client.chat.completions.create(**kwargs)
            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta
        except Exception as exc:
            raise provider_error(exc) from exc

    async def test_connection(self) -> None:
        try:
            await self._client.models.list()
        except Exception as exc:
            raise provider_error(exc, connection=True) from exc

    async def aclose(self) -> None:
        await self._client.close()


class OpenAICompatibleEmbedder:
    """Embedding adapter for any OpenAI-compatible API."""

    def __init__(self, client: AsyncOpenAI):
        self._client = client

    async def embed(self, texts: Sequence[str], *, model: str) -> list[list[float]]:
        try:
            resp = await self._client.embeddings.create(model=model, input=list(texts))
        except Exception as exc:
            raise provider_error(exc) from exc
        ordered = sorted(resp.data, key=lambda item: getattr(item, "index", 0))
        vectors = [list(item.embedding) for item in ordered]
        validate_vectors(vectors, expected=len(texts))
        return vectors

    async def test_connection(self) -> None:
        try:
            await self._client.models.list()
        except Exception as exc:
            raise provider_error(exc, connection=True) from exc

    async def aclose(self) -> None:
        await self._client.close()
