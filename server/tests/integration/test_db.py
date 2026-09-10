from sqlalchemy import text


async def test_db_select_one(db_session):
    result = await db_session.execute(text("SELECT 1"))
    assert result.scalar_one() == 1
