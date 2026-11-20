"""Shared fixtures and test-plan rules.

Rules enforced here (docs/testing/test-plan.md, aligned with ISO/IEC 29119):
- every test names the PRD requirement it covers with ``@pytest.mark.req(...)``;
- the test level (unit, integration, system) comes from the test's folder.

No test may reach a real provider or need a credential (hard rule 1). The only
external process is a local PostgreSQL 16 container.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine

from keepair.config import REPO_ROOT, Settings
from keepair.demo.seed import demo_clock, issue_demo_credentials, seed

LEVELS = ("unit", "integration", "system")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    missing = []
    for item in items:
        parts = Path(str(item.fspath)).parts
        level = next((p for p in parts if p in LEVELS), None)
        if level is None:
            raise pytest.UsageError(
                f"{item.nodeid}: tests must live in tests/unit, integration or system"
            )
        item.add_marker(pytest.mark.level(level))
        marker = item.get_closest_marker("req")
        if marker is None or not marker.args:
            missing.append(item.nodeid)
    if missing:
        raise pytest.UsageError(
            "Tests without a PRD requirement (@pytest.mark.req):\n  " + "\n  ".join(missing)
        )


def alembic_config(database_url: str) -> Config:
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    cfg.attributes["database_url"] = database_url
    return cfg


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    """A throwaway PostgreSQL 16. Set KEEPAIR_TEST_DATABASE_URL to reuse one."""
    preset = os.environ.get("KEEPAIR_TEST_DATABASE_URL")
    if preset:
        yield preset
        return
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:16-alpine", driver="psycopg") as container:
        yield container.get_connection_url()


@pytest.fixture(scope="session")
def migrated_engine(database_url: str) -> Iterator[Engine]:
    command.upgrade(alembic_config(database_url), "head")
    engine = create_engine(database_url)
    yield engine
    engine.dispose()


@pytest.fixture
def engine(migrated_engine: Engine) -> Engine:
    """Database reset to the seeded demo data before each test."""
    with migrated_engine.begin() as conn:
        seed(conn, demo_clock())
        issue_demo_credentials(conn)
    return migrated_engine


@pytest.fixture
def settings(database_url: str) -> Settings:
    return Settings(env="test", database_url=database_url)


@pytest.fixture
def unreachable_engine() -> Iterator[Engine]:
    """An engine pointing at a closed local port: every query fails fast."""
    engine = create_engine(
        "postgresql+psycopg://nobody@127.0.0.1:1/none", connect_args={"connect_timeout": 1}
    )
    yield engine
    engine.dispose()
