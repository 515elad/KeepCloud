from datetime import timedelta

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from keepair.demo.seed import DEMO_CLOCK_AT, demo_clock, seed
from keepair.health import HealthStatus, read_health, record_heartbeat
from keepair.schema import metadata
from tests.conftest import alembic_config

TABLES = sorted(metadata.tables)


def snapshot(conn) -> dict[str, list[tuple]]:
    return {
        t: [tuple(r) for r in conn.execute(text(f"SELECT * FROM {t} ORDER BY 1"))]  # noqa: S608
        for t in TABLES
    }


@pytest.mark.req("v1.4 Section 2.3 (Alembic migrations)", "ISO 27001 A.8.32")
def test_migrations_create_exactly_the_declared_tables(engine):
    found = set(inspect(engine).get_table_names()) - {"alembic_version"}
    assert found == set(TABLES)


@pytest.mark.req("v1.4 Section 2.3 (Alembic migrations)", "ISO 27001 A.8.32")
def test_migration_downgrade_and_upgrade_round_trip(database_url, engine):
    cfg = alembic_config(database_url)
    command.downgrade(cfg, "base")
    probe = create_engine(database_url)
    try:
        assert set(inspect(probe).get_table_names()) == {"alembic_version"}
    finally:
        probe.dispose()
        command.upgrade(cfg, "head")


@pytest.mark.req("Hard rule 2 (deterministic demo data)")
def test_seed_twice_gives_identical_data(engine):
    with engine.begin() as conn:
        seed(conn, demo_clock())
        first = snapshot(conn)
        seed(conn, demo_clock())
        second = snapshot(conn)
    assert first == second
    assert first["demo_placeholder"] == [(1, "Placeholder amount", 2_050_000_000, "USD")]
    assert ("demo_clock", "2026-01-15T09:00:00Z") in first["app_meta"]
    assert first["heartbeats"] == []


@pytest.mark.req("FR-02 (money as BIGINT micro-units)", "ISO 4217")
def test_money_column_is_bigint_and_currency_is_checked(engine):
    columns = {c["name"]: c for c in inspect(engine).get_columns("demo_placeholder")}
    assert str(columns["amount_micro"]["type"]) == "BIGINT"
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(text("INSERT INTO demo_placeholder VALUES (2, 'x', 1, 'usd')"))
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(text("INSERT INTO demo_placeholder VALUES (2, 'x', -1, 'USD')"))


@pytest.mark.req("ISO 8601", "Hard rule 4 (UTC storage)")
def test_timestamps_are_stored_with_timezone(engine):
    for table in ("heartbeats", "alerts"):
        for column in inspect(engine).get_columns(table):
            if "TIMESTAMP" in str(column["type"]):
                assert column["type"].timezone is True, f"{table}.{column['name']}"


@pytest.mark.req("FR-21", "SEC-37", "UX-6")
def test_heartbeat_moves_a_component_from_unknown_through_every_state(engine):
    clock = demo_clock()
    with engine.begin() as conn:
        assert {h.status for h in read_health(conn, clock)} == {HealthStatus.UNKNOWN}
        record_heartbeat(conn, "gateway", clock)
        record_heartbeat(conn, "gateway", clock)  # second heartbeat updates, never duplicates

        def gateway():
            return next(h for h in read_health(conn, clock) if h.component.id == "gateway")

        assert gateway().status is HealthStatus.HEALTHY
        assert gateway().last_heartbeat_at == DEMO_CLOCK_AT
        clock.advance(timedelta(seconds=61))
        assert gateway().status is HealthStatus.DEGRADED
        clock.advance(timedelta(seconds=120))
        assert gateway().status is HealthStatus.FAILING
        others = [h for h in read_health(conn, clock) if h.component.id != "gateway"]
        assert {h.status for h in others} == {HealthStatus.UNKNOWN}
        conn.rollback()


@pytest.mark.req("FR-21", "SEC-37")
def test_heartbeat_for_unlisted_component_is_refused(engine):
    with engine.begin() as conn, pytest.raises(ValueError, match="unknown component"):
        record_heartbeat(conn, "made-up", demo_clock())
