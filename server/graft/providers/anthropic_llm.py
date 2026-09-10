from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

from anthropic import AsyncAnthropic

from .base import ChatMessage, provider_error

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
        try:
            async with self._client.messages.stream(**kwargs) as stream:
                async for text in stream.text_stream:
                    if text:
                        yield text
        except Exception as exc:
            raise provider_error(exc) from exc

    async def test_connection(self) -> None:
        try:
            await self._client.models.list()
        except Exception as exc:
            raise provider_error(exc, connection=True) from exc

    async def aclose(self) -> None:
        await self._client.close()
