from sqlalchemy import inspect


async def test_core_tables_exist(db_engine):
    async with db_engine.connect() as conn:
        tables = await conn.run_sync(lambda c: inspect(c).get_table_names())
    for name in ["user", "bots", "bot_members", "documents", "conversations", "messages"]:
        assert name in tables
