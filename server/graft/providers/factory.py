from __future__ import annotations

from anthropic import AsyncAnthropic
from cryptography.fernet import InvalidToken
from openai import AsyncOpenAI

from ..security.crypto import decrypt
from .anthropic_llm import AnthropicLLM
from .base import PROVIDER_CONFIG, EmbeddingProvider, LLMProvider, ProviderError
from .config import EmbeddingConfig, LLMConfig
from .openai_compatible import OpenAICompatibleEmbedder, OpenAICompatibleLLM

# Providers reachable through an OpenAI-compatible endpoint, with their default base URLs.
_OPENAI_COMPATIBLE_DEFAULTS = {
    "openai_compatible": None,  # OpenAI (or an admin-provided base_url for Ollama/LM Studio)
    "google": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "mistral": "https://api.mistral.ai/v1",
}


# Defaults for callers that do not care. The worker overrides max_retries=0: the
# job already owns retry/backoff, and stacking SDK retries on top of it multiplies
# both the wall clock and the bill without anyone deciding to.
DEFAULT_TIMEOUT = 60.0
DEFAULT_MAX_RETRIES = 2


def _resolve_key(api_key: str | None, encrypted: bool) -> str:
    if api_key and encrypted:
        try:
            return decrypt(api_key)
        except InvalidToken as exc:
            raise ProviderError(PROVIDER_CONFIG) from exc
    return api_key or "not-needed"


def _openai_client(
    config: LLMConfig | EmbeddingConfig,
    default_base_url: str | None,
    *,
    timeout: float,
    max_retries: int,
) -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=_resolve_key(config.api_key, config.api_key_encrypted),
        base_url=config.base_url or default_base_url,
        timeout=timeout,
        max_retries=max_retries,
    )


def _anthropic_client(config: LLMConfig, *, timeout: float, max_retries: int) -> AsyncAnthropic:
    return AsyncAnthropic(
        api_key=_resolve_key(config.api_key, config.api_key_encrypted),
        base_url=config.base_url or None,
        timeout=timeout,
        max_retries=max_retries,
    )


def build_llm(
    config: LLMConfig,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> LLMProvider:
    if config.provider == "anthropic":
        return AnthropicLLM(_anthropic_client(config, timeout=timeout, max_retries=max_retries))
    if config.provider in _OPENAI_COMPATIBLE_DEFAULTS:
        return OpenAICompatibleLLM(
            _openai_client(
                config,
                _OPENAI_COMPATIBLE_DEFAULTS[config.provider],
                timeout=timeout,
                max_retries=max_retries,
            )
        )
    raise ProviderError(PROVIDER_CONFIG)


def build_embedder(
    config: EmbeddingConfig,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> EmbeddingProvider:
    # Anthropic ships no embedding API: this is a misconfigured bot, not an outage.
    if config.provider == "anthropic":
        raise ProviderError(PROVIDER_CONFIG)
    if config.provider in _OPENAI_COMPATIBLE_DEFAULTS:
        return OpenAICompatibleEmbedder(
            _openai_client(
                config,
                _OPENAI_COMPATIBLE_DEFAULTS[config.provider],
                timeout=timeout,
                max_retries=max_retries,
            )
        )
    raise ProviderError(PROVIDER_CONFIG)
