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
