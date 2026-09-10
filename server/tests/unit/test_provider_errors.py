import asyncio
from types import SimpleNamespace

import httpx
import openai
import pytest

from graft.providers.base import (
    ProviderConnectionError,
    ProviderError,
    provider_error,
    validate_vectors,
)
from graft.providers.openai_compatible import (
    OpenAICompatibleEmbedder,
    OpenAICompatibleLLM,
)

SECRET = "sk-live-DO-NOT-LEAK-4242"


def _request() -> httpx.Request:
    return httpx.Request("POST", "https://provider.test/v1/chat/completions")


def _status_error(cls, status: int, message: str = "upstream said no"):
    response = httpx.Response(status, request=_request())
    return cls(message, response=response, body=None)


@pytest.mark.parametrize(
    ("exc", "code", "retryable"),
    [
        (_status_error(openai.AuthenticationError, 401), "provider_auth", False),
        (_status_error(openai.PermissionDeniedError, 403), "provider_auth", False),
        (_status_error(openai.RateLimitError, 429), "provider_rate_limit", True),
        (_status_error(openai.InternalServerError, 503), "provider_unavailable", True),
        (_status_error(openai.BadRequestError, 400), "provider_config", False),
        (_status_error(openai.NotFoundError, 404), "provider_config", False),
        (_status_error(openai.UnprocessableEntityError, 422), "provider_invalid_response", False),
        (openai.APITimeoutError(request=_request()), "provider_timeout", True),
        (openai.APIConnectionError(request=_request()), "provider_unavailable", True),
        (TimeoutError(), "provider_timeout", True),
        (RuntimeError("who knows"), "provider_unavailable", False),
    ],
)
def test_provider_error_classifies_sdk_failures(exc, code, retryable):
    err = provider_error(exc)
    assert isinstance(err, ProviderError)
    assert err.code == code
    assert err.retryable is retryable


def test_provider_error_is_idempotent():
    original = ProviderError("provider_auth")
    assert provider_error(original) is original


def test_provider_error_message_never_leaks_secrets(caplog):
    with caplog.at_level("DEBUG"):
        err = provider_error(_status_error(openai.AuthenticationError, 401, f"key {SECRET} bad"))
    assert SECRET not in str(err)
    assert str(err) == "provider_auth"
    assert SECRET not in caplog.text


def test_connection_error_stays_a_provider_error():
    err = provider_error(_status_error(openai.AuthenticationError, 401), connection=True)
    assert isinstance(err, ProviderConnectionError)
    assert isinstance(err, ProviderError)
    assert err.code == "provider_auth"


# --- vector validation -------------------------------------------------------


def test_validate_vectors_accepts_well_formed_batch():
    validate_vectors([[0.1, 0.2], [0.3, 0.4]], expected=2)


@pytest.mark.parametrize(
    "vectors",
    [
        [[0.1, 0.2]],                      # too few
        [[0.1, 0.2], [0.3, 0.4], [0.5]],   # too many
        [[0.1, 0.2], []],                  # empty vector
        [[0.1, 0.2], [0.3]],               # ragged dimensions
        [[0.1, 0.2], [float("nan"), 0.4]],  # not finite
        [[0.1, 0.2], [float("inf"), 0.4]],
        [[0.1, 0.2], [0.0, 0.0]],          # zero norm
    ],
)
def test_validate_vectors_rejects_bad_batches(vectors):
    with pytest.raises(ProviderError) as excinfo:
        validate_vectors(vectors, expected=2)
    assert excinfo.value.code == "provider_invalid_response"


# --- adapters normalize --------------------------------------------------------


class _RaisingCompletions:
    def __init__(self, exc, *, during_iteration: bool):
        self._exc = exc
        self._during_iteration = during_iteration

    async def create(self, **kwargs):
        if not self._during_iteration:
            raise self._exc

        async def _gen():
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="partial"))]
            )
            raise self._exc

        return _gen()


def _client(*, completions=None, embeddings=None, models_error=None):
    async def _list():
        if models_error:
            raise models_error
        return SimpleNamespace(data=[])

    return SimpleNamespace(
        chat=SimpleNamespace(completions=completions),
        embeddings=embeddings,
        models=SimpleNamespace(list=_list),
    )


async def test_stream_chat_normalizes_error_before_first_token():
    exc = _status_error(openai.RateLimitError, 429, f"slow down {SECRET}")
    llm = OpenAICompatibleLLM(_client(completions=_RaisingCompletions(exc, during_iteration=False)))
    with pytest.raises(ProviderError) as excinfo:
        async for _ in llm.stream_chat([{"role": "user", "content": "hi"}], model="m"):
            pass
    assert excinfo.value.code == "provider_rate_limit"
    assert SECRET not in str(excinfo.value)


async def test_stream_chat_normalizes_error_during_iteration():
    exc = _status_error(openai.InternalServerError, 500)
    llm = OpenAICompatibleLLM(_client(completions=_RaisingCompletions(exc, during_iteration=True)))
    seen = []
    with pytest.raises(ProviderError) as excinfo:
        async for delta in llm.stream_chat([{"role": "user", "content": "hi"}], model="m"):
            seen.append(delta)
    assert seen == ["partial"]
    assert excinfo.value.code == "provider_unavailable"


async def test_stream_chat_lets_cancellation_through():
    completions = _RaisingCompletions(asyncio.CancelledError(), during_iteration=True)
    llm = OpenAICompatibleLLM(_client(completions=completions))
    with pytest.raises(asyncio.CancelledError):
        async for _ in llm.stream_chat([{"role": "user", "content": "hi"}], model="m"):
            pass


class _Embeddings:
    def __init__(self, vectors=None, exc=None):
        self._vectors = vectors
        self._exc = exc

    async def create(self, **kwargs):
        if self._exc:
            raise self._exc
        return SimpleNamespace(data=[SimpleNamespace(embedding=v) for v in self._vectors])


async def test_embed_normalizes_provider_failure():
    exc = _status_error(openai.AuthenticationError, 401, f"bad {SECRET}")
    embedder = OpenAICompatibleEmbedder(_client(embeddings=_Embeddings(exc=exc)))
    with pytest.raises(ProviderError) as excinfo:
        await embedder.embed(["a"], model="m")
    assert excinfo.value.code == "provider_auth"
    assert SECRET not in str(excinfo.value)


async def test_embed_rejects_short_batch():
    embedder = OpenAICompatibleEmbedder(_client(embeddings=_Embeddings(vectors=[[0.1, 0.2]])))
    with pytest.raises(ProviderError) as excinfo:
        await embedder.embed(["a", "b"], model="m")
    assert excinfo.value.code == "provider_invalid_response"


async def test_test_connection_maps_code():
    client = _client(models_error=_status_error(openai.AuthenticationError, 401, SECRET))
    with pytest.raises(ProviderConnectionError) as excinfo:
        await OpenAICompatibleLLM(client).test_connection()
    assert excinfo.value.code == "provider_auth"
    assert SECRET not in str(excinfo.value)
