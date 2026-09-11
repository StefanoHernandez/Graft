"""What the visitor receives, and what must never reach them.

The rule these tests protect: an answer is only delivered once every label in it
points at a document that was actually retrieved.
"""
import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from graft.models import Bot, Chunk, Document
from graft.providers.base import ProviderError
from graft.rag.prompt import ABSTENTION
from graft.rag.service import answer_question

FINGERPRINT = "a" * 64
ALPHA = [1.0, 0.0, 0.0]
BETA = [0.0, 1.0, 0.0]


class _Embedder:
    def __init__(self, vector=ALPHA):
        self.vector = vector
        self.calls = 0

    async def embed(self, texts, *, model):
        self.calls += 1
        return [list(self.vector) for _ in texts]


class _LLM:
    """Streams a scripted answer in small pieces, like a real provider."""

    def __init__(self, answer="The port is 8443 [S1]."):
        self.answer = answer
        self.calls = 0
        self.seen_messages = None

    async def stream_chat(self, messages, *, model, temperature=0.0, max_tokens=None):
        self.calls += 1
        self.seen_messages = messages
        for index in range(0, len(self.answer), 7):
            yield self.answer[index : index + 7]


class _NeverCalledLLM:
    async def stream_chat(self, messages, **kwargs):
        raise AssertionError("the model must not be called")
        yield ""  # pragma: no cover


class _FailingLLM:
    def __init__(self, exc, before=None):
        self.exc = exc
        self.before = before

    async def stream_chat(self, messages, **kwargs):
        if self.before:
            yield self.before
        raise self.exc


@pytest.fixture
async def maker(db_engine):
    return async_sessionmaker(db_engine, expire_on_commit=False)


async def _bot_with_chunks(maker, chunks=((ALPHA, "Port 8443 must be reachable."),),
                           system_prompt=""):
    async with maker() as session:
        bot = Bot(name="b", widget_key=f"wk_{uuid.uuid4().hex}", system_prompt=system_prompt)
        session.add(bot)
        await session.flush()
        document = Document(bot_id=bot.id, filename="install.md", mime_type="text/markdown",
                            status="ready", embedding_fingerprint=FINGERPRINT)
        session.add(document)
        await session.flush()
        for position, (vector, content) in enumerate(chunks):
            session.add(Chunk(
                document_id=document.id, bot_id=bot.id, content=content, embedding=vector,
                embedding_dim=len(vector), position=position, chunk_metadata={"page": 1},
            ))
        await session.commit()
        return bot


async def _collect(session, bot, llm, embedder=None, question="What port?", **kwargs):
    events = []
    async for event in answer_question(
        session,
        bot=bot,
        embedder=embedder or _Embedder(),
        llm=llm,
        question=question,
        history=kwargs.pop("history", []),
        fingerprint=FINGERPRINT,
        embedding_model="e",
        chat_model="c",
        **kwargs,
    ):
        events.append(event)
    return events


def _kinds(events):
    return [e["event"] for e in events]


async def test_no_context_answers_without_calling_the_model(maker):
    bot = await _bot_with_chunks(maker)
    async with maker() as session:
        events = await _collect(
            session, bot, _NeverCalledLLM(), embedder=_Embedder(vector=BETA), min_score=0.5
        )
    assert _kinds(events) == ["done"]
    done = events[0]["data"]
    assert done["answer"] == ABSTENTION
    assert done["citations"] == []
    assert done["grounding"] == "no_context"


async def test_a_grounded_answer_streams_and_then_reports_its_sources(maker):
    bot = await _bot_with_chunks(maker)
    llm = _LLM()
    async with maker() as session:
        events = await _collect(session, bot, llm)
    assert _kinds(events)[-1] == "done"
    assert "delta" in _kinds(events)
    streamed = "".join(e["data"]["text"] for e in events if e["event"] == "delta")
    done = events[-1]["data"]
    assert streamed == done["answer"] == "The port is 8443 [S1]."
    assert done["grounding"] == "retrieved"
    citation = done["citations"][0]
    assert citation["id"] == "S1"
    assert citation["filename"] == "install.md"
    assert citation["page"] == 1
    assert citation["excerpt"]


async def test_an_invented_label_is_refused_after_the_fact(maker):
    """The text was already streamed; the answer is still not delivered as valid."""
    bot = await _bot_with_chunks(maker)
    async with maker() as session:
        events = await _collect(session, bot, _LLM("Use port 9000 [S99]."))
    assert "done" not in _kinds(events)
    assert _kinds(events)[-1] == "error"
    assert events[-1]["data"]["code"] == "invalid_citation"


async def test_an_answer_with_no_citation_at_all_is_refused(maker):
    bot = await _bot_with_chunks(maker)
    async with maker() as session:
        events = await _collect(session, bot, _LLM("The port is 8443."))
    assert _kinds(events)[-1] == "error"
    assert events[-1]["data"]["code"] == "invalid_citation"


async def test_abstaining_with_context_is_a_valid_answer(maker):
    bot = await _bot_with_chunks(maker)
    async with maker() as session:
        events = await _collect(session, bot, _LLM(ABSTENTION))
    done = events[-1]
    assert done["event"] == "done"
    assert done["data"]["grounding"] == "no_context"
    assert done["data"]["citations"] == []


async def test_only_the_cited_sources_are_reported(maker):
    bot = await _bot_with_chunks(
        maker, chunks=((ALPHA, "first source"), ([0.99, 0.01, 0.0], "second source")),
    )
    async with maker() as session:
        events = await _collect(session, bot, _LLM("Only the first one matters [S1]."))
    citations = events[-1]["data"]["citations"]
    assert [c["id"] for c in citations] == ["S1"]


async def test_a_provider_failure_midstream_ends_the_answer_without_a_done(maker):
    bot = await _bot_with_chunks(maker)
    async with maker() as session:
        events = await _collect(
            session, bot,
            _FailingLLM(ProviderError("provider_unavailable", retryable=True), before="The po"),
        )
    assert _kinds(events) == ["delta", "error"]
    assert events[-1]["data"]["code"] == "provider_unavailable"


async def test_a_provider_failure_before_the_first_token_is_reported_the_same_way(maker):
    bot = await _bot_with_chunks(maker)
    async with maker() as session:
        events = await _collect(session, bot, _FailingLLM(ProviderError("provider_auth")))
    assert _kinds(events) == ["error"]
    assert events[-1]["data"]["code"] == "provider_auth"


async def test_the_context_budget_caps_what_is_sent(maker):
    bot = await _bot_with_chunks(
        maker,
        chunks=(
            (ALPHA, "A" * 400),
            ([0.99, 0.01, 0.0], "B" * 400),
            ([0.98, 0.02, 0.0], "C" * 400),
        ),
    )
    llm = _LLM("Answer [S1].")
    async with maker() as session:
        await _collect(session, bot, llm, context_budget=500)
    block = llm.seen_messages[-1]["content"]
    assert "[S1]" in block
    # The third source cannot fit, so it is never labelled or sent.
    assert "[S3]" not in block
    assert "C" * 400 not in block


async def test_the_bots_own_prompt_reaches_the_model(maker):
    bot = await _bot_with_chunks(maker, system_prompt="Answer in Italian.")
    llm = _LLM("La porta è 8443 [S1].")
    async with maker() as session:
        await _collect(session, bot, llm)
    system = llm.seen_messages[0]["content"]
    assert "Answer in Italian." in system
    assert ABSTENTION in system


async def test_history_is_passed_through_as_turns(maker):
    bot = await _bot_with_chunks(maker)
    llm = _LLM()
    history = [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"}]
    async with maker() as session:
        await _collect(session, bot, llm, history=history)
    assert llm.seen_messages[1:3] == history


async def test_abandoning_the_answer_closes_the_provider_stream(maker):
    """A visitor who closes the tab must not leave a generation running."""
    bot = await _bot_with_chunks(maker)

    class _TrackedLLM:
        def __init__(self):
            self.closed = False

        async def stream_chat(self, messages, **kwargs):
            try:
                for piece in ["one ", "two ", "three "]:
                    yield piece
            finally:
                self.closed = True

    llm = _TrackedLLM()
    async with maker() as session:
        stream = answer_question(
            session, bot=bot, embedder=_Embedder(), llm=llm, question="q", history=[],
            fingerprint=FINGERPRINT, embedding_model="e", chat_model="c",
        )
        assert (await anext(stream))["event"] == "delta"
        await stream.aclose()
    assert llm.closed is True
