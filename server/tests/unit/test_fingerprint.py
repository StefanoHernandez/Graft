import pytest

from graft.providers.config import EmbeddingConfig
from graft.providers.fingerprint import embedding_fingerprint


def _config(**overrides) -> EmbeddingConfig:
    base = {"provider": "openai_compatible", "model": "text-embedding-3-small", "api_key": "a"}
    return EmbeddingConfig(**{**base, **overrides})


def test_key_rotation_keeps_fingerprint():
    first = EmbeddingConfig(provider="openai_compatible", model="m", api_key="a")
    second = first.model_copy(update={"api_key": "b"})
    assert embedding_fingerprint(first) == embedding_fingerprint(second)
    assert embedding_fingerprint(first.model_copy(update={"model": "other"})) != embedding_fingerprint(first)


def test_fingerprint_is_a_sha256_hex_digest():
    value = embedding_fingerprint(_config())
    assert len(value) == 64
    assert set(value) <= set("0123456789abcdef")


def test_fingerprint_ignores_the_api_key_entirely():
    assert embedding_fingerprint(_config(api_key=None)) == embedding_fingerprint(_config(api_key="x"))
    assert embedding_fingerprint(_config(api_key_encrypted=False)) == embedding_fingerprint(_config())


@pytest.mark.parametrize("field,value", [("provider", "mistral"), ("model", "other-model")])
def test_fingerprint_changes_with_provider_or_model(field, value):
    assert embedding_fingerprint(_config(**{field: value})) != embedding_fingerprint(_config())


def test_default_endpoint_is_resolved_explicitly():
    # An unset base_url and the provider's own default are the same index.
    explicit = _config(base_url="https://api.openai.com/v1")
    assert embedding_fingerprint(explicit) == embedding_fingerprint(_config(base_url=None))


def test_trailing_slash_and_whitespace_do_not_split_the_index():
    assert embedding_fingerprint(_config(base_url="https://api.openai.com/v1/")) == \
        embedding_fingerprint(_config(base_url=" https://api.openai.com/v1 "))


def test_different_endpoint_is_a_different_index():
    # Same model name served by a local runtime is not the same vector space.
    local = _config(base_url="http://localhost:11434/v1")
    assert embedding_fingerprint(local) != embedding_fingerprint(_config())


def test_google_and_mistral_defaults_come_from_the_factory():
    from graft.providers.factory import _OPENAI_COMPATIBLE_DEFAULTS

    for provider, default in _OPENAI_COMPATIBLE_DEFAULTS.items():
        if default is None:
            continue
        unset = _config(provider=provider, base_url=None)
        explicit = _config(provider=provider, base_url=default)
        assert embedding_fingerprint(unset) == embedding_fingerprint(explicit)
