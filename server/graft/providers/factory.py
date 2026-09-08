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
