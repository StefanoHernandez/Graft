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
