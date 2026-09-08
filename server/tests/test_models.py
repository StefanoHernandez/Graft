import uuid

from sqlalchemy import select

from graft.models import Bot


async def test_bot_roundtrip(db_engine):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        bot = Bot(
            name="Docs bot",
            widget_key=f"wk_{uuid.uuid4().hex}",
            allowed_origins=["https://example.com"],
            llm_config={"provider": "openai_compatible"},
            embedding_config={"provider": "openai_compatible"},
            system_prompt="Answer only from context.",
            theme={"color": "#0055ff"},
            retrieval_config={"top_k": 5},
        )
        session.add(bot)
        await session.commit()

        found = (await session.execute(select(Bot).where(Bot.name == "Docs bot"))).scalar_one()
        assert found.allowed_origins == ["https://example.com"]
        assert found.retrieval_config["top_k"] == 5
        assert found.id is not None
