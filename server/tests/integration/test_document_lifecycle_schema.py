"""Migration 0003 must be additive: legacy rows survive, columns can come back off.

Runs against its own throwaway database in the same container, so the session
schema other integration tests rely on is never downgraded under them.
"""
import uuid

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

TEMP_DB = "graft_migration_0003"


def _alembic_config(url: str) -> Config:
    cfg = Config("alembic.ini")
    cfg.set_main_option("script_location", "migrations")
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


@pytest.fixture
def temp_db_url(pg):
    admin = create_engine(pg.sync_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{TEMP_DB}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{TEMP_DB}"'))
    url = pg.sync_url.rsplit("/", 1)[0] + f"/{TEMP_DB}"
    yield url
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{TEMP_DB}" WITH (FORCE)'))
    admin.dispose()


def _columns(engine, table):
    with engine.connect() as conn:
        return {c["name"]: c for c in inspect(conn).get_columns(table)}


def test_0003_preserves_legacy_rows_and_downgrades(temp_db_url):
    cfg = _alembic_config(temp_db_url)
    command.upgrade(cfg, "0002")

    engine = create_engine(temp_db_url)
    bot_id, doc_id = uuid.uuid4(), uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO bots (id, name, widget_key, system_prompt)"
                " VALUES (:id, 'legacy', :key, '')"
            ),
            {"id": bot_id, "key": f"k-{bot_id}"},
        )
        conn.execute(
            text(
                "INSERT INTO documents (id, bot_id, filename, mime_type, status, chunk_count)"
                " VALUES (:id, :bot, 'old.pdf', 'application/pdf', 'ready', 1)"
            ),
            {"id": doc_id, "bot": bot_id},
        )
        conn.execute(
            text(
                "INSERT INTO chunks (id, document_id, bot_id, content, embedding_dim,"
                " embedding, position) VALUES (:id, :doc, :bot, 'legacy text', 2,"
                " '[0.1,0.2]', 0)"
            ),
            {"id": uuid.uuid4(), "doc": doc_id, "bot": bot_id},
        )

    command.upgrade(cfg, "head")

    columns = _columns(engine, "documents")
    for name in [
        "storage_key",
        "source_sha256",
        "embedding_fingerprint",
        "ingestion_run_id",
        "lease_expires_at",
    ]:
        assert columns[name]["nullable"] is True, f"{name} must be nullable for legacy rows"
    assert columns["attempt_count"]["nullable"] is False

    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT filename, status, chunk_count, storage_key, embedding_fingerprint,"
                " attempt_count FROM documents WHERE id = :id"
            ),
            {"id": doc_id},
        ).one()
        assert row.filename == "old.pdf"
        assert row.status == "ready"
        assert row.chunk_count == 1
        assert row.storage_key is None
        assert row.embedding_fingerprint is None
        assert row.attempt_count == 0
        assert conn.execute(text("SELECT content FROM chunks")).scalar() == "legacy text"

    message_columns = _columns(engine, "messages")
    assert message_columns["request_id"]["nullable"] is True
    assert message_columns["status"]["nullable"] is False

    command.downgrade(cfg, "0002")
    assert "storage_key" not in _columns(engine, "documents")
    assert "status" not in _columns(engine, "messages")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT filename FROM documents")).scalar() == "old.pdf"
    engine.dispose()


def test_message_status_is_constrained(temp_db_url):
    cfg = _alembic_config(temp_db_url)
    command.upgrade(cfg, "head")
    engine = create_engine(temp_db_url)
    bot_id, conv_id = uuid.uuid4(), uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO bots (id, name, widget_key, system_prompt)"
                " VALUES (:id, 'b', :key, '')"
            ),
            {"id": bot_id, "key": f"k-{bot_id}"},
        )
        conn.execute(
            text(
                "INSERT INTO conversations (id, bot_id, visitor_session)"
                " VALUES (:id, :bot, 's')"
            ),
            {"id": conv_id, "bot": bot_id},
        )
    # Broad Exception: the check violation surfaces as a driver-specific subclass.
    with pytest.raises(Exception), engine.begin() as conn:  # noqa: B017
            conn.execute(
                text(
                    "INSERT INTO messages (id, conversation_id, role, content, status)"
                    " VALUES (:id, :conv, 'user', 'hi', 'bogus')"
                ),
                {"id": uuid.uuid4(), "conv": conv_id},
            )
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO messages (id, conversation_id, role, content)"
                " VALUES (:id, :conv, 'user', 'hi')"
            ),
            {"id": uuid.uuid4(), "conv": conv_id},
        )
        assert conn.execute(text("SELECT status FROM messages")).scalar() == "completed"
    engine.dispose()
