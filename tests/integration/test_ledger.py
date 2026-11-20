"""Ledger under concurrency, expiry and failure (FR-05, SEC-35)."""

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import OperationalError

from keepair.clock import FixedClock
from keepair.demo.seed import demo_clock
from keepair.formulas import _tenant
from keepair.gateway import ledger
from keepair.gateway.errors import GatewayError
from keepair.rng import seeded_rng, system_rng
from keepair.schema import budgets, reservations

U = 1_000_000


def reserve(conn, gw_or_engine, budget_id, cost, **kwargs):
    return ledger.reserve(
        conn, clock=demo_clock(), rng=system_rng(), tenant_id=_tenant(conn),
        request_id=uuid.uuid4(), budget_id=budget_id, cost_micros=cost, **kwargs,
    )  # fmt: skip


def hard_budget(gw, name="Code Review Agent"):
    """A hard-limit project budget and its path, with exactly `room` left on itself."""
    return gw.budget(name)


@pytest.mark.req("FR-05 (concurrency)", "ISO 25010 reliability")
def test_reserve_never_exceeds_cap_under_200_concurrent_requests(gw, database_url):
    budget = hard_budget(gw)
    cost = 10 * U
    room = 50 * cost  # room for exactly 50 of the 200 requests
    gw.execute(
        "UPDATE budgets SET cap_micros = committed_micros + reserved_micros + :room WHERE id = :id",
        room=room,
        id=budget.id,
    )
    cap = gw.budget("Code Review Agent").cap_micros
    engine = create_engine(database_url, pool_size=20, max_overflow=0, pool_timeout=120)
    violations, stop = [], threading.Event()

    def watch():  # samples the counters while the requests race
        while not stop.is_set():
            with engine.connect() as conn:
                row = conn.execute(
                    select(budgets.c.committed_micros, budgets.c.reserved_micros).where(
                        budgets.c.id == budget.id
                    )
                ).one()
            if row.committed_micros + row.reserved_micros > cap:
                violations.append(tuple(row))

    def attempt(_):
        try:
            with engine.begin() as conn:
                reserve(conn, gw, budget.id, cost)
            return "RESERVED"
        except GatewayError as err:
            return err.code

    watcher = threading.Thread(target=watch)
    watcher.start()
    try:
        with ThreadPoolExecutor(max_workers=200) as pool:
            results = list(pool.map(attempt, range(200)))
    finally:
        stop.set()
        watcher.join()
        engine.dispose()

    assert results.count("RESERVED") == 50 and results.count("BUDGET_EXHAUSTED") == 150
    after = gw.budget("Code Review Agent")
    # Tolerance for reservations is zero: the estimator is an upper bound (D-04).
    assert after.committed_micros + after.reserved_micros == cap and violations == []
    for name in ("Agents", "Engineering", "Northwind Labs"):  # the whole path moved together
        parent_before = {"Agents": 2_950, "Engineering": 4_750, "Northwind Labs": 5_420}[name] * U
        assert gw.budget(name).reserved_micros == parent_before + 50 * cost
    assert (
        len(
            gw.rows(
                "SELECT 1 FROM reservations WHERE budget_id = :id AND state = 'RESERVED' AND credential_id IS NULL AND agent_id IS NULL",
                id=budget.id,
            )
        )
        == 50
    )


@pytest.mark.req("FR-05 (ordered row locks)")
def test_opposite_paths_do_not_deadlock(gw, database_url):
    """Sibling projects share parents; many interleaved reservations must all finish."""
    a, b = gw.budget("Build Assistant").id, gw.budget("Log Summarizer").id
    engine = create_engine(database_url, pool_size=16, max_overflow=0, pool_timeout=60)

    def attempt(i):
        with engine.begin() as conn:
            reserve(conn, gw, a if i % 2 else b, 1)
        return True

    try:
        with ThreadPoolExecutor(max_workers=16) as pool:
            assert all(pool.map(attempt, range(120)))
    finally:
        engine.dispose()


@pytest.mark.req("FR-05 (settle once)", "B-h")
def test_concurrent_settles_commit_once(gw, database_url):
    budget = gw.budget("Build Assistant")
    before = budget.committed_micros
    with gw.engine.begin() as conn:
        r = reserve(conn, gw, budget.id, 100)
    engine = create_engine(database_url, pool_size=10)

    def settle(_):
        with engine.begin() as conn:
            return (
                ledger.settle(conn, r.reservation_id, clock=demo_clock(), actual_micros=60)
                is not None
            )

    try:
        with ThreadPoolExecutor(max_workers=10) as pool:
            done = list(pool.map(settle, range(10)))
    finally:
        engine.dispose()
    assert done.count(True) == 1
    after = gw.budget("Build Assistant")
    assert after.committed_micros == before + 60 and after.reserved_micros == budget.reserved_micros
    with gw.engine.begin() as conn:  # a closed reservation cannot be released or claimed
        assert not ledger.release(conn, r.reservation_id, clock=demo_clock())
        assert not ledger.claim_for_dispatch(conn, r.reservation_id)


@pytest.mark.req("FR-05", "v1.4 test list")
def test_db_failure_mid_reserve_leaves_no_partial_state(gw, monkeypatch):
    before = gw.rows(
        "SELECT id, committed_micros, reserved_micros, version FROM budgets ORDER BY id"
    )

    def fail(*args, **kwargs):
        raise OperationalError("INSERT", {}, Exception("connection lost"))

    monkeypatch.setattr("keepair.gateway.service.Gateway._record", fail)
    response = gw.chat("Build Assistant")  # hard limit: fails closed
    # Since phase 3 this is a policy answer (the budget's fail mode), not a bare 503.
    assert response.status_code == 403 and response.json()["error"]["code"] == "BUDGET_FAIL_CLOSED"
    monkeypatch.undo()
    assert (
        gw.rows("SELECT id, committed_micros, reserved_micros, version FROM budgets ORDER BY id")
        == before
    )
    assert not gw.rows("SELECT 1 FROM reservations WHERE credential_id IS NOT NULL")
    assert not gw.rows(
        "SELECT 1 FROM gateway_decisions"
    )  # the refusal is in the spool, to be replayed
    assert gw.app.state.spool.stats().waiting == 1 and gw.app.state.spool.stats().waiting_usage == 0


@pytest.mark.req("SEC-06", "S-34")
def test_no_record_no_dispatch(gw, monkeypatch):
    """If the decision cannot be recorded in the ledger, a hard-limit request is denied
    and nothing is sent. (Soft and monitor budgets record to the spool first: test_fail_open.)"""

    def fail(*args, **kwargs):
        raise OperationalError("INSERT", {}, Exception("disk full"))

    assert gw.chat("Research Agent").status_code == 202  # seen just before the failure
    monkeypatch.setattr("keepair.gateway.service.Gateway._record", fail)
    assert gw.chat("Build Assistant").status_code == 403
    assert gw.chat("Research Agent").status_code == 403  # approval budgets fail closed too
    assert not gw.provider.called
    # Two refusals, plus the first one's result that could not be stored for replay.
    assert gw.metrics.value("keepair_failures_total", code="DATABASE_UNREACHABLE") >= 2


@pytest.mark.req("SEC-35", "S-09")
def test_expiry_uses_db_clock(gw):
    """An application clock that is years off does not move the expiry."""
    wrong_clock = FixedClock(datetime(1999, 1, 1, tzinfo=UTC))
    with gw.engine.begin() as conn:
        r = ledger.reserve(
            conn, clock=wrong_clock, rng=seeded_rng(1), tenant_id=_tenant(conn),
            request_id=uuid.uuid4(), budget_id=gw.budget("Build Assistant").id, cost_micros=1,
            limits=ledger.Limits(ttl_s=240),
        )  # fmt: skip
        row = conn.execute(
            text("SELECT expires_at, now() AS db_now, created_at FROM reservations WHERE id = :id"),
            {"id": r.reservation_id},
        ).one()
    assert row.expires_at - row.db_now == timedelta(seconds=240)
    assert row.created_at.year == 1999  # the injected clock is only a label here


@pytest.mark.req("FR-05 (reservation TTL)", "B-i")
def test_expired_reservation_settles_and_alerts(gw):
    budget = gw.budget("Build Assistant")
    with gw.engine.begin() as conn:
        r = reserve(conn, gw, budget.id, 500, limits=ledger.Limits(ttl_s=0))
        live = reserve(conn, gw, budget.id, 7, limits=ledger.Limits(ttl_s=600))
    seen = gw.app.state.maintenance.tick()
    assert seen["ledger"]
    [row] = gw.rows(
        "SELECT state, usage_known, actual_micros FROM reservations WHERE id = :id",
        id=r.reservation_id,
    )
    assert tuple(row) == ("EXPIRED", False, 500)
    after = gw.budget("Build Assistant")
    assert after.committed_micros == budget.committed_micros + 500
    assert after.reserved_micros == budget.reserved_micros + 7  # the live one is untouched
    assert (
        gw.rows("SELECT state FROM reservations WHERE id = :id", id=live.reservation_id)[0].state
        == "RESERVED"
    )
    assert gw.metrics.value("keepair_failures_total", code="RESERVATION_EXPIRED") == 1
    assert gw.rows("SELECT 1 FROM alerts WHERE code = 'RESERVATION_EXPIRED'")
    gw.app.state.maintenance.tick()  # a second sweep changes nothing
    assert gw.budget("Build Assistant").committed_micros == budget.committed_micros + 500
    # The seeded long-running reservations are never swept.
    assert (
        len(
            gw.rows(
                "SELECT 1 FROM reservations WHERE state = 'RESERVED' AND credential_id IS NULL AND expires_at > now() + interval '10 years'"
            )
        )
        == 10
    )


@pytest.mark.req("FR-11", "FR-05 (HELD)")
def test_hold_expires_and_releases_budget(gw):
    budget = gw.budget("Research Agent")
    with gw.engine.begin() as conn:
        r = reserve(conn, gw, budget.id, 900, limits=ledger.Limits(hold_ttl_s=0))
    assert (
        r.state == "HELD"
        and gw.budget("Research Agent").reserved_micros == budget.reserved_micros + 900
    )
    gw.app.state.maintenance.tick()
    [row] = gw.rows(
        "SELECT state, actual_micros FROM reservations WHERE id = :id", id=r.reservation_id
    )
    assert tuple(row) == ("EXPIRED", 0)
    after = gw.budget("Research Agent")
    assert (after.committed_micros, after.reserved_micros) == (
        budget.committed_micros,
        budget.reserved_micros,
    )
    assert (
        gw.metrics.value("keepair_failures_total", code="RESERVATION_EXPIRED") == 0
    )  # nothing was sent


@pytest.mark.req("FR-05", "FR-04")
def test_seeded_reserved_amounts_are_backed_by_reservations(gw):
    """Every budget's reserved counter equals the open reservations on its path."""
    rows = gw.rows(
        "SELECT b.id, b.reserved_micros, coalesce(sum(r.reserved_micros), 0) AS open "
        "FROM budgets b LEFT JOIN reservations r ON b.id = ANY(r.budget_path) AND r.state IN ('RESERVED','HELD','APPROVED') "
        "GROUP BY b.id"
    )
    assert len(rows) == 22 and all(r.reserved_micros == r.open for r in rows)
    gw.chat("Build Assistant")
    gw.chat("Research Agent")
    rows = gw.rows(
        "SELECT b.reserved_micros, coalesce(sum(r.reserved_micros), 0) AS open "
        "FROM budgets b LEFT JOIN reservations r ON b.id = ANY(r.budget_path) AND r.state IN ('RESERVED','HELD','APPROVED') "
        "GROUP BY b.id"
    )
    assert all(r.reserved_micros == r.open for r in rows)


@pytest.mark.req("D-02", "B-a", "B-n7")
def test_customer_key_project_cannot_activate_hard_limit(gw):
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError, match="customer-held key"):
        gw.execute(
            "UPDATE projects SET key_custody = 'CUSTOMER' WHERE name = 'Build Assistant'"
        )  # hard
    with pytest.raises(IntegrityError, match="customer-held key"):
        gw.execute(
            "UPDATE projects SET key_custody = 'CUSTOMER' WHERE name = 'Research Agent'"
        )  # approval
    gw.execute(
        "UPDATE projects SET key_custody = 'CUSTOMER' WHERE name = 'Call Notes'"
    )  # monitor: fine
    # Call Notes has no owner in the demo data. Give it one, so that the custody rule and
    # not the owner rule (FR-17, phase 5) is what refuses the hard limit below.
    gw.execute(
        "UPDATE budgets SET owner_user_id = (SELECT id FROM users WHERE username = 'bob.admin') "
        "WHERE id = :id",
        id=gw.budget("Call Notes").id,
    )
    for policy in ("HARD", "APPROVAL"):
        with pytest.raises(IntegrityError, match="customer-held key"):
            gw.execute(
                "UPDATE budgets SET policy = :p WHERE id = :id",
                p=policy,
                id=gw.budget("Call Notes").id,
            )
    gw.execute("UPDATE budgets SET policy = 'SOFT' WHERE id = :id", id=gw.budget("Call Notes").id)
    assert gw.rows("SELECT 1 FROM reservations LIMIT 1")  # the rule left other data alone
    assert reservations.c.budget_path is not None
