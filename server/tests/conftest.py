import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from graft.main import app as _app


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
