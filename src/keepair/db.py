"""Database engine factory."""

from __future__ import annotations

from sqlalchemy import Engine, create_engine

from keepair.config import Settings


def make_engine(settings: Settings) -> Engine:
    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": settings.db_connect_timeout_s},
    )
