import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from graft.models import Bot, Chunk, Document


async def test_chunk_roundtrip(db_engine):
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        bot = Bot(name="b", widget_key=f"wk_{uuid.uuid4().hex}")
        session.add(bot)
        await session.flush()
        doc = Document(bot_id=bot.id, filename="f.txt", mime_type="text/plain")
        session.add(doc)
        await session.flush()
        session.add(Chunk(
            document_id=doc.id, bot_id=bot.id, content="hello",
            embedding=[0.1, 0.2, 0.3], embedding_dim=3, position=0,
            chunk_metadata={"k": "v"},
        ))
        await session.commit()

        got = (await session.execute(
            select(Chunk).where(Chunk.document_id == doc.id))).scalar_one()
        assert got.content == "hello"
        assert got.embedding_dim == 3
        assert len(got.embedding) == 3
        assert got.chunk_metadata == {"k": "v"}
        assert got.position == 0
