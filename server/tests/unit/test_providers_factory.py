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


def test_build_llm_anthropic():
    from graft.providers.anthropic_llm import AnthropicLLM
    from graft.providers.config import LLMConfig
    from graft.providers.factory import build_llm
    from graft.security import crypto

    cfg = LLMConfig(
        provider="anthropic",
        model="claude-sonnet-5",
        api_key=crypto.encrypt("sk-ant-xyz"),
        api_key_encrypted=True,
    )
    provider = build_llm(cfg)
    assert isinstance(provider, AnthropicLLM)
    assert provider._client.api_key == "sk-ant-xyz"


def test_build_llm_google_uses_default_base_url():
    from graft.providers.config import LLMConfig
    from graft.providers.factory import build_llm
    from graft.providers.openai_compatible import OpenAICompatibleLLM

    provider = build_llm(LLMConfig(
        provider="google", model="gemini-2.5-flash", api_key=None, api_key_encrypted=False))
    assert isinstance(provider, OpenAICompatibleLLM)
    assert "generativelanguage.googleapis.com/v1beta/openai" in str(provider._client.base_url)


def test_build_llm_mistral_uses_default_base_url():
    from graft.providers.config import LLMConfig
    from graft.providers.factory import build_llm
    from graft.providers.openai_compatible import OpenAICompatibleLLM

    provider = build_llm(LLMConfig(
        provider="mistral", model="mistral-large-latest", api_key=None, api_key_encrypted=False))
    assert isinstance(provider, OpenAICompatibleLLM)
    assert "api.mistral.ai/v1" in str(provider._client.base_url)


def test_build_llm_explicit_base_url_overrides_default():
    from graft.providers.config import LLMConfig
    from graft.providers.factory import build_llm

    provider = build_llm(LLMConfig(
        provider="mistral", model="m", base_url="http://proxy.local/v1",
        api_key=None, api_key_encrypted=False))
    assert "proxy.local/v1" in str(provider._client.base_url)


def test_build_embedder_google_and_mistral():
    from graft.providers.config import EmbeddingConfig
    from graft.providers.factory import build_embedder
    from graft.providers.openai_compatible import OpenAICompatibleEmbedder

    g = build_embedder(EmbeddingConfig(
        provider="google", model="text-embedding-004", api_key=None, api_key_encrypted=False))
    m = build_embedder(EmbeddingConfig(
        provider="mistral", model="mistral-embed", api_key=None, api_key_encrypted=False))
    assert isinstance(g, OpenAICompatibleEmbedder)
    assert isinstance(m, OpenAICompatibleEmbedder)
    assert "generativelanguage.googleapis.com/v1beta/openai" in str(g._client.base_url)
    assert "api.mistral.ai/v1" in str(m._client.base_url)


def test_decrypt_failure_raises_provider_error():
    from graft.providers.base import ProviderError
    from graft.providers.config import LLMConfig
    from graft.providers.factory import build_llm

    # A syntactically invalid Fernet token -> decrypt fails -> ProviderError (not InvalidToken).
    with pytest.raises(ProviderError):
        build_llm(LLMConfig(
            provider="openai_compatible", model="m",
            api_key="not-a-valid-fernet-token", api_key_encrypted=True))
