from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from graft.config import get_settings
from graft.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Runtime uses asyncpg; Alembic uses the sync psycopg driver on the same DB.
# An explicit url set by the caller wins, so tests and ops tooling can migrate a
# database other than the configured one.
url = config.get_main_option("sqlalchemy.url") or get_settings().database_url
url = url.replace("+asyncpg", "+psycopg")
config.set_main_option("sqlalchemy.url", url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
