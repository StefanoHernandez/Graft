
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from testcontainers.community.postgres import PostgresContainer

from graft.main import app


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture(scope="session")
def pg():
    with PostgresContainer("pgvector/pgvector:pg16", username="graft",
                           password="graft", dbname="graft") as container:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(5432)
        base = f"graft:graft@{host}:{port}/graft"
        container.sync_url = f"postgresql+psycopg://{base}"
        container.async_url = f"postgresql+asyncpg://{base}"
        yield container


@pytest_asyncio.fixture
async def db_engine(pg):
    engine = create_async_engine(pg.async_url)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        yield session
