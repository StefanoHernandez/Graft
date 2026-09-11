"""Question in, grounded answer out.

Two decisions shape everything here:

- **No context, no call.** If nothing clears the similarity threshold the answer
  is a fixed refusal, produced without spending a request on a model that has
  nothing to work from.
- **Citations are checked after the stream.** The text was already shown, so this
  cannot make a wrong answer right; what it does is refuse to *deliver* an answer
  that cites a document nobody retrieved. It checks that a label exists, not that
  the sentence follows from it — entailment is not something this can prove.
"""
from __future__ import annotations

import re
from collections.abc import AsyncIterator, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Bot
from ..providers.base import ChatMessage, EmbeddingProvider, LLMProvider, ProviderError
from .prompt import ABSTENTION, build_messages
from .retrieval import DEFAULT_MIN_SCORE, DEFAULT_TOP_K, RetrievedChunk, retrieve

DEFAULT_CONTEXT_BUDGET = 6000
DEFAULT_MAX_TOKENS = 512
EXCERPT_CHARS = 400

_LABEL = re.compile(r"\[S(\d+)\]")


async def answer_question(
    session: AsyncSession,
    *,
    bot: Bot,
    embedder: EmbeddingProvider,
    llm: LLMProvider,
    question: str,
    history: Sequence[ChatMessage],
    fingerprint: str,
    embedding_model: str,
    chat_model: str,
    top_k: int = DEFAULT_TOP_K,
    min_score: float = DEFAULT_MIN_SCORE,
    context_budget: int = DEFAULT_CONTEXT_BUDGET,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> AsyncIterator[dict]:
    """Yield `delta`, then exactly one `done` **or** one `error`."""
    try:
        vectors = await embedder.embed([question], model=embedding_model)
        sources = await retrieve(
            session, bot.id, fingerprint, vectors[0], top_k=top_k, min_score=min_score
        )
    except ProviderError as exc:
        yield _error(exc.code)
        return

    sources = _within_budget(sources, context_budget)
    if not sources:
        yield _done(ABSTENTION, [], "no_context")
        return

    messages = build_messages(question, history, sources, bot.system_prompt or "")
    pieces: list[str] = []
    try:
        async for delta in llm.stream_chat(
            messages, model=chat_model, temperature=0.0, max_tokens=max_tokens
        ):
            pieces.append(delta)
            yield {"event": "delta", "data": {"text": delta}}
    except ProviderError as exc:
        yield _error(exc.code)
        return

    answer = "".join(pieces).strip()
    cited = _validate_citations(answer, sources)
    if cited is None:
        yield _error("invalid_citation")
        return
    if not cited:
        # The model used the exact refusal: a legitimate answer with nothing to cite.
        yield _done(answer, [], "no_context")
        return
    yield _done(answer, [_citation(label, source) for label, source in cited], "retrieved")


def _within_budget(sources: list[RetrievedChunk], budget: int) -> list[RetrievedChunk]:
    """Keep the best-scoring sources that fit. Labels are assigned after this.

    Trimming first is what keeps a label from pointing at text the model never saw.
    """
    kept: list[RetrievedChunk] = []
    used = 0
    for source in sources:
        if used + len(source.content) > budget:
            break
        kept.append(source)
        used += len(source.content)
    return kept


def _validate_citations(
    answer: str, sources: Sequence[RetrievedChunk]
) -> list[tuple[str, RetrievedChunk]] | None:
    """Return the cited sources, or None when the answer cannot be trusted.

    None means either an invented label, or a normal-looking answer that cites
    nothing — both are answers a visitor could not check.
    """
    labels = [int(number) for number in _LABEL.findall(answer)]
    if any(number < 1 or number > len(sources) for number in labels):
        return None
    if not labels:
        return [] if _is_abstention(answer) else None
    seen: list[tuple[str, RetrievedChunk]] = []
    for number in dict.fromkeys(labels):
        seen.append((f"S{number}", sources[number - 1]))
    return seen


def _is_abstention(answer: str) -> bool:
    return answer.strip().rstrip(".").casefold() == ABSTENTION.rstrip(".").casefold()


def _citation(label: str, source: RetrievedChunk) -> dict:
    return {
        "id": label,
        "document_id": str(source.document_id),
        "filename": source.filename,
        "page": source.page,
        "heading": source.heading,
        # The excerpt travels with the answer: a source the visitor cannot read is
        # not a source. It also means an admin must only upload material meant to
        # be public.
        "excerpt": source.content[:EXCERPT_CHARS],
    }


def _done(answer: str, citations: list[dict], grounding: str) -> dict:
    return {"event": "done", "data": {"answer": answer, "citations": citations,
                                      "grounding": grounding}}


def _error(code: str) -> dict:
    return {"event": "error", "data": {"code": code}}
