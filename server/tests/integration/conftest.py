import os
import pathlib
import secrets

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
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
def migrated(pg, tmp_path_factory):
    os.environ["DATABASE_URL"] = pg.async_url
    os.environ["STORAGE_ROOT"] = str(tmp_path_factory.mktemp("uploads"))
    os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())
    os.environ.setdefault("JWT_SECRET", secrets.token_urlsafe(32))
    from graft.config import get_settings
    get_settings.cache_clear()
    cfg = Config("alembic.ini")
    cfg.set_main_option("script_location", "migrations")
    cfg.set_main_option("sqlalchemy.url", pg.sync_url)
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(scope="session")
def cleanup_engine(pg):
    """One engine for teardown, so truncating does not cost a connection pool per test."""
    return create_async_engine(pg.async_url, poolclass=NullPool)


@pytest_asyncio.fixture(autouse=True)
async def clean_tables(migrated, cleanup_engine):
    """Every integration test starts from empty tables.

    The container is session-scoped, so without this a test silently depends on
    what ran before it — which is how a suite starts failing only in one order.
    """
    yield
    async with cleanup_engine.begin() as conn:
        await conn.execute(
            text('TRUNCATE bots, documents, chunks, conversations, messages, "user" CASCADE')
        )


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
