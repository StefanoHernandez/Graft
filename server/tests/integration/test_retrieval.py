"""Retrieval must never compare vectors that are not comparable.

Every exclusion below is a way of returning a confident answer built on the
wrong corpus: another bot's documents, a failed upload, or chunks embedded by a
different model that happen to have the same length.
"""
import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from graft.models import Bot, Chunk, Document
from graft.rag import retrieve

FINGERPRINT = "a" * 64
OTHER_FINGERPRINT = "b" * 64

# Three orthogonal directions, so scores are obvious rather than incidental.
ALPHA = [1.0, 0.0, 0.0]
BETA = [0.0, 1.0, 0.0]
GAMMA = [0.0, 0.0, 1.0]
NEAR_ALPHA = [0.9, 0.1, 0.0]


@pytest.fixture
async def maker(db_engine):
    return async_sessionmaker(db_engine, expire_on_commit=False)


async def _corpus(
    maker,
    *,
    fingerprint=FINGERPRINT,
    status="ready",
    chunks=((ALPHA, "alpha text"), (BETA, "beta text")),
    filename="manual.pdf",
    metadata=None,
):
    async with maker() as session:
        bot = Bot(name="b", widget_key=f"wk_{uuid.uuid4().hex}")
        session.add(bot)
        await session.flush()
        document = Document(
            bot_id=bot.id,
            filename=filename,
            mime_type="application/pdf",
            status=status,
            embedding_fingerprint=fingerprint,
        )
        session.add(document)
        await session.flush()
        for position, (vector, content) in enumerate(chunks):
            session.add(
                Chunk(
                    document_id=document.id,
                    bot_id=bot.id,
                    content=content,
                    embedding=vector,
                    embedding_dim=len(vector),
                    position=position,
                    chunk_metadata=metadata if metadata is not None else {"page": position + 1},
                )
            )
        await session.commit()
        return bot, document


async def test_returns_the_closest_chunk_first(maker):
    bot, _ = await _corpus(maker)
    async with maker() as session:
        results = await retrieve(session, bot.id, FINGERPRINT, ALPHA, min_score=0.0)
    assert [r.content for r in results] == ["alpha text", "beta text"]
    assert results[0].score == pytest.approx(1.0)
    assert results[1].score == pytest.approx(0.0, abs=1e-6)


async def test_provenance_travels_with_the_chunk(maker):
    bot, document = await _corpus(
        maker, filename="handbook.pdf", metadata={"page": 7, "heading": "Returns"}
    )
    async with maker() as session:
        results = await retrieve(session, bot.id, FINGERPRINT, ALPHA, min_score=0.0)
    first = results[0]
    assert first.filename == "handbook.pdf"
    assert first.page == 7
    assert first.heading == "Returns"
    assert first.document_id == document.id


async def test_missing_provenance_is_none_not_an_error(maker):
    bot, _ = await _corpus(maker, metadata={})
    async with maker() as session:
        results = await retrieve(session, bot.id, FINGERPRINT, ALPHA, min_score=0.0)
    assert results[0].page is None
    assert results[0].heading is None


async def test_threshold_is_what_produces_an_abstention(maker):
    bot, _ = await _corpus(maker)
    async with maker() as session:
        strict = await retrieve(session, bot.id, FINGERPRINT, GAMMA, min_score=0.5)
        loose = await retrieve(session, bot.id, FINGERPRINT, GAMMA, min_score=-1.0)
    assert strict == []
    assert len(loose) == 2


async def test_top_k_limits_the_context(maker):
    bot, _ = await _corpus(
        maker,
        chunks=[(NEAR_ALPHA, f"chunk {i}") for i in range(6)],
    )
    async with maker() as session:
        results = await retrieve(session, bot.id, FINGERPRINT, ALPHA, top_k=2, min_score=0.0)
    assert len(results) == 2


async def test_ties_break_on_chunk_id_so_the_order_is_stable(maker):
    bot, _ = await _corpus(
        maker, chunks=[(ALPHA, "first"), (ALPHA, "second"), (ALPHA, "third")]
    )
    async with maker() as session:
        first_run = await retrieve(session, bot.id, FINGERPRINT, ALPHA, min_score=0.0)
        second_run = await retrieve(session, bot.id, FINGERPRINT, ALPHA, min_score=0.0)
    assert [r.chunk_id for r in first_run] == sorted(r.chunk_id for r in first_run)
    assert [r.chunk_id for r in first_run] == [r.chunk_id for r in second_run]


async def test_another_bots_corpus_is_never_searched(maker):
    mine, _ = await _corpus(maker, chunks=[(ALPHA, "mine")])
    theirs, _ = await _corpus(maker, chunks=[(ALPHA, "theirs")])
    async with maker() as session:
        results = await retrieve(session, mine.id, FINGERPRINT, ALPHA, min_score=0.0)
    assert [r.content for r in results] == ["mine"]
    assert theirs.id != mine.id


async def test_a_different_fingerprint_is_a_different_vector_space(maker):
    bot, _ = await _corpus(maker, fingerprint=OTHER_FINGERPRINT)
    async with maker() as session:
        results = await retrieve(session, bot.id, FINGERPRINT, ALPHA, min_score=-1.0)
    assert results == []


async def test_same_dimension_different_model_is_still_excluded(maker):
    """The trap the dimension check alone would walk into."""
    bot, _ = await _corpus(maker, chunks=[(ALPHA, "from model A")])
    async with maker() as session:
        other_space = await retrieve(session, bot.id, OTHER_FINGERPRINT, ALPHA, min_score=-1.0)
        own_space = await retrieve(session, bot.id, FINGERPRINT, ALPHA, min_score=-1.0)
    assert other_space == []
    assert len(own_space) == 1


async def test_a_query_of_another_dimension_returns_nothing_instead_of_erroring(maker):
    bot, _ = await _corpus(maker)
    async with maker() as session:
        results = await retrieve(session, bot.id, FINGERPRINT, [1.0, 0.0], min_score=-1.0)
    assert results == []


async def test_mixed_dimensions_in_one_bot_do_not_break_the_query(maker):
    bot, _ = await _corpus(maker, chunks=[(ALPHA, "three dims")])
    async with maker() as session:
        document = Document(
            bot_id=bot.id, filename="other.pdf", mime_type="application/pdf",
            status="ready", embedding_fingerprint=FINGERPRINT,
        )
        session.add(document)
        await session.flush()
        session.add(Chunk(
            document_id=document.id, bot_id=bot.id, content="four dims",
            embedding=[1.0, 0.0, 0.0, 0.0], embedding_dim=4, position=0, chunk_metadata={},
        ))
        await session.commit()
        results = await retrieve(session, bot.id, FINGERPRINT, ALPHA, min_score=-1.0)
    assert [r.content for r in results] == ["three dims"]


@pytest.mark.parametrize("status", ["pending", "processing", "failed"])
async def test_only_ready_documents_are_searchable(maker, status):
    bot, _ = await _corpus(maker, status=status)
    async with maker() as session:
        results = await retrieve(session, bot.id, FINGERPRINT, ALPHA, min_score=-1.0)
    assert results == []


async def test_legacy_chunks_without_a_fingerprint_are_excluded(maker):
    bot, _ = await _corpus(maker, fingerprint=None)
    async with maker() as session:
        results = await retrieve(session, bot.id, FINGERPRINT, ALPHA, min_score=-1.0)
    assert results == []


@pytest.mark.parametrize(
    "bad", [[], [0.0, 0.0, 0.0], [float("nan"), 1.0, 0.0], [float("inf"), 1.0, 0.0]]
)
async def test_a_meaningless_query_vector_is_refused(maker, bad):
    bot, _ = await _corpus(maker)
    async with maker() as session:
        with pytest.raises(ValueError):
            await retrieve(session, bot.id, FINGERPRINT, bad)


async def test_an_empty_corpus_is_not_an_error(maker):
    async with maker() as session:
        bot = Bot(name="empty", widget_key=f"wk_{uuid.uuid4().hex}")
        session.add(bot)
        await session.commit()
        assert await retrieve(session, bot.id, FINGERPRINT, ALPHA, min_score=-1.0) == []
