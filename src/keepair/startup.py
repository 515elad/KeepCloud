"""Checks made when a service starts (SEC-23)."""

from __future__ import annotations

from sqlalchemy import Engine, select

from keepair.config import Settings
from keepair.schema import app_meta


class DemoDataInProduction(RuntimeError):
    """Demo data found in a production database."""


def refuse_test_material(engine: Engine, settings: Settings) -> None:
    """Demo data carries demo accounts, a known password and demo gateway credentials.
    A service configured as production refuses to start on it."""
    if settings.env != "prod":
        return
    with engine.connect() as conn:
        demo = conn.execute(select(app_meta.c.value).where(app_meta.c.key == "demo")).scalar()
    if demo == "true":
        raise DemoDataInProduction(
            "This database holds demo data and demo credentials. Refusing to start in production."
        )
