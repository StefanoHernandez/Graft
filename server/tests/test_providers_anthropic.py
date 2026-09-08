from types import SimpleNamespace

import pytest

from graft.providers.anthropic_llm import AnthropicLLM
from graft.providers.base import ProviderConnectionError


class _FakeStreamCM:
    def __init__(self, texts):
        self._texts = texts

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    @property
    def text_stream(self):
        async def _gen():
            for t in self._texts:
                yield t

        return _gen()


class _FakeMessages:
    def __init__(self, texts):
        self._texts = texts
        self.calls = []

    def stream(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeStreamCM(self._texts)


class _FakeModels:
    def __init__(self, error=None):
        self._error = error

    async def list(self):
        if self._error:
            raise self._error
        return SimpleNamespace(data=[])


def _fake_client(texts=None, models_error=None):
    return SimpleNamespace(messages=_FakeMessages(texts or []), models=_FakeModels(models_error))


async def test_stream_chat_yields_text_and_skips_empty():
    client = _fake_client(texts=["Hel", "", "lo"])
    llm = AnthropicLLM(client)
    out = [t async for t in llm.stream_chat(
        [{"role": "user", "content": "hi"}], model="claude", max_tokens=32)]
    assert out == ["Hel", "lo"]
    sent = client.messages.calls[0]
    assert sent["model"] == "claude"
    assert sent["max_tokens"] == 32
    assert sent["extra_body"] == {"temperature": 0.0}


async def test_system_messages_are_extracted():
    client = _fake_client(texts=["ok"])
    llm = AnthropicLLM(client)
    _ = [t async for t in llm.stream_chat(
        [
            {"role": "system", "content": "Be terse."},
            {"role": "system", "content": "Cite sources."},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "prev"},
        ],
        model="claude",
        temperature=0.3,
    )]
    sent = client.messages.calls[0]
    assert sent["system"] == "Be terse.\n\nCite sources."
    assert sent["messages"] == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "prev"},
    ]
    assert sent["extra_body"] == {"temperature": 0.3}


async def test_max_tokens_defaults_to_1024():
    client = _fake_client(texts=["x"])
    llm = AnthropicLLM(client)
    _ = [t async for t in llm.stream_chat([{"role": "user", "content": "hi"}], model="claude")]
    assert client.messages.calls[0]["max_tokens"] == 1024


async def test_no_system_key_when_no_system_messages():
    client = _fake_client(texts=["x"])
    llm = AnthropicLLM(client)
    _ = [t async for t in llm.stream_chat([{"role": "user", "content": "hi"}], model="claude")]
    assert "system" not in client.messages.calls[0]


async def test_test_connection_ok_and_error_wrapping():
    await AnthropicLLM(_fake_client()).test_connection()
    with pytest.raises(ProviderConnectionError):
        await AnthropicLLM(_fake_client(models_error=RuntimeError("boom"))).test_connection()
