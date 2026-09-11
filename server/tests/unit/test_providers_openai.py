from types import SimpleNamespace

import pytest

from graft.providers.base import ProviderConnectionError
from graft.providers.openai_compatible import (
    OpenAICompatibleEmbedder,
    OpenAICompatibleLLM,
)


def _chunk(content):
    # Mimics openai ChatCompletionChunk: choices[0].delta.content
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=content))])


class _FakeCompletions:
    def __init__(self, chunks):
        self._chunks = chunks
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)

        async def _gen():
            for c in self._chunks:
                yield c

        return _gen()


class _FakeEmbeddings:
    def __init__(self, vectors):
        self._vectors = vectors
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(data=[SimpleNamespace(embedding=v) for v in self._vectors])


class _FakeEmbeddingsIndexed:
    def __init__(self, data):
        self._data = data
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(data=self._data)


class _FakeModels:
    def __init__(self, error=None):
        self._error = error

    async def list(self):
        if self._error:
            raise self._error
        return SimpleNamespace(data=[])


def _fake_client(chunks=None, vectors=None, models_error=None):
    return SimpleNamespace(
        chat=SimpleNamespace(completions=_FakeCompletions(chunks or [])),
        embeddings=_FakeEmbeddings(vectors or []),
        models=_FakeModels(models_error),
    )


async def test_stream_chat_yields_only_nonempty_content():
    client = _fake_client(chunks=[_chunk("Hello"), _chunk(None), _chunk(""), _chunk(" world")])
    llm = OpenAICompatibleLLM(client)
    out = [tok async for tok in llm.stream_chat(
        [{"role": "user", "content": "hi"}], model="m", max_tokens=64)]
    assert out == ["Hello", " world"]
    # max_tokens forwarded, stream requested
    sent = client.chat.completions.calls[0]
    assert sent["stream"] is True
    assert sent["model"] == "m"
    assert sent["max_tokens"] == 64


async def test_stream_chat_omits_max_tokens_when_none():
    client = _fake_client(chunks=[_chunk("a")])
    llm = OpenAICompatibleLLM(client)
    _ = [tok async for tok in llm.stream_chat([{"role": "user", "content": "x"}], model="m")]
    assert "max_tokens" not in client.chat.completions.calls[0]


async def test_embed_returns_vectors_in_order():
    client = _fake_client(vectors=[[0.1, 0.2], [0.3, 0.4]])
    emb = OpenAICompatibleEmbedder(client)
    result = await emb.embed(["a", "b"], model="e")
    assert result == [[0.1, 0.2], [0.3, 0.4]]
    assert client.embeddings.calls[0]["input"] == ["a", "b"]


async def test_test_connection_ok():
    llm = OpenAICompatibleLLM(_fake_client())
    await llm.test_connection()  # no raise


async def test_test_connection_wraps_errors():
    client = _fake_client(models_error=RuntimeError("boom"))
    llm = OpenAICompatibleLLM(client)
    with pytest.raises(ProviderConnectionError):
        await llm.test_connection()


async def test_stream_chat_skips_chunks_without_choices():
    # A usage-only / content-filter chunk with choices=[] must be skipped, not crash.
    client = _fake_client(chunks=[
        SimpleNamespace(choices=[]),
        _chunk("hi"),
        SimpleNamespace(choices=[]),
    ])
    llm = OpenAICompatibleLLM(client)
    out = [tok async for tok in llm.stream_chat([{"role": "user", "content": "x"}], model="m")]
    assert out == ["hi"]


async def test_embed_returns_index_ordered_vectors():
    # Even if the server returns data out of order, embed() must sort by index.
    client = SimpleNamespace(
        embeddings=_FakeEmbeddingsIndexed([
            SimpleNamespace(index=1, embedding=[9.0]),
            SimpleNamespace(index=0, embedding=[8.0]),
        ]),
    )
    emb = OpenAICompatibleEmbedder(client)
    assert await emb.embed(["a", "b"], model="e") == [[8.0], [9.0]]


class _ClosableStream:
    """Mimics the SDK's response stream, and remembers whether it was closed."""

    def __init__(self, chunks):
        self._chunks = chunks
        self.closed = False

    def __aiter__(self):
        async def _gen():
            for chunk in self._chunks:
                yield chunk
        return _gen()

    async def close(self):
        self.closed = True


class _StreamingCompletions:
    def __init__(self, stream):
        self.stream = stream

    async def create(self, **kwargs):
        return self.stream


def _client_with(stream):
    return SimpleNamespace(chat=SimpleNamespace(completions=_StreamingCompletions(stream)))


async def test_the_response_stream_is_closed_after_a_full_read():
    stream = _ClosableStream([_chunk("hi"), _chunk(" there")])
    llm = OpenAICompatibleLLM(_client_with(stream))
    assert [d async for d in llm.stream_chat([], model="m")] == ["hi", " there"]
    assert stream.closed is True


async def test_the_response_stream_is_closed_when_the_reader_walks_away():
    """A visitor who closes the tab must not leave an HTTP response open.

    Left to the garbage collector this surfaces later as "generator didn't stop
    after athrow()" from the HTTP layer, and holds the connection until then.
    """
    stream = _ClosableStream([_chunk("one"), _chunk("two"), _chunk("three")])
    llm = OpenAICompatibleLLM(_client_with(stream))
    answer = llm.stream_chat([], model="m")
    assert await anext(answer) == "one"
    await answer.aclose()
    assert stream.closed is True
