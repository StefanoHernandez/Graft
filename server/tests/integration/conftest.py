import os
import pathlib

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from testcontainers.community.postgres import PostgresContainer

from graft.db import get_session
from graft.main import app as _app

_HERE = pathlib.Path(__file__).parent


def pytest_collection_modifyitems(items):
    for item in items:
        if _HERE in pathlib.Path(item.path).parents:
            item.add_marker(pytest.mark.integration)


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


@pytest.fixture(scope="session", autouse=True)
def migrated(pg):
    os.environ["DATABASE_URL"] = pg.async_url
    from graft.config import get_settings
    get_settings.cache_clear()
    cfg = Config("alembic.ini")
    cfg.set_main_option("script_location", "migrations")
    cfg.set_main_option("sqlalchemy.url", pg.sync_url)
    command.upgrade(cfg, "head")
    yield


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


@pytest_asyncio.fixture
async def ready_client(db_engine):
    maker = async_sessionmaker(db_engine, expire_on_commit=False)

    async def _override():
        async with maker() as session:
            yield session

    _app.dependency_overrides[get_session] = _override
    transport = ASGITransport(app=_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    _app.dependency_overrides.clear()
