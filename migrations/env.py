"""Alembic environment. The database URL comes from settings, never from a file."""

from alembic import context
from sqlalchemy import create_engine

from keepair.config import Settings
from keepair.schema import metadata

config = context.config
target_metadata = metadata


def _url() -> str:
    settings = Settings()
    return (
        config.attributes.get("database_url")
        or settings.owner_database_url
        or settings.database_url
    )


def run_migrations_online() -> None:
    engine = create_engine(_url())
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    raise SystemExit("Offline migrations are not supported.")
run_migrations_online()
