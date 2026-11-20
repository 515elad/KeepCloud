"""Heartbeats, the scripted demo traffic and a latency check."""

from collections import Counter
from datetime import timedelta

import pytest
from sqlalchemy.exc import OperationalError

from keepair.demo.seed import demo_clock, issue_demo_credentials, seed
from keepair.demo.traffic import TOTAL, build_plan, run_plan
from keepair.health import HealthStatus, read_health
from tests.gateway_harness import make_gateway


@pytest.mark.req("FR-21 (heartbeats)", "SEC-37", "UX-6")
def test_upkeep_round_writes_heartbeats_for_what_it_saw_working(gw):
    with gw.engine.connect() as conn:
        assert {h.status for h in read_health(conn, gw.clock)} == {HealthStatus.UNKNOWN}
    assert gw.app.state.maintenance.tick() == {
        "policy_sync": True,
        "ledger": True,
        "alerting": True,
        "gateway": True,
    }
    with gw.engine.connect() as conn:
        health = {h.component.id: h.status for h in read_health(conn, gw.clock)}
    assert health == {
        "gateway": HealthStatus.HEALTHY, "policy_sync": HealthStatus.HEALTHY,
        "ledger": HealthStatus.HEALTHY, "alerting": HealthStatus.HEALTHY,
        "egress": HealthStatus.UNKNOWN, "data_sources": HealthStatus.UNKNOWN,
    }  # fmt: skip
    gw.clock.advance(timedelta(seconds=45))  # the gateway stops: no new heartbeat
    with gw.engine.connect() as conn:
        health = {h.component.id: h.status for h in read_health(conn, gw.clock)}
    assert (
        health["policy_sync"] is HealthStatus.DEGRADED and health["gateway"] is HealthStatus.HEALTHY
    )
    gw.clock.advance(timedelta(seconds=200))
    with gw.engine.connect() as conn:
        assert {h.status for h in read_health(conn, gw.clock) if h.last_heartbeat_at} == {
            HealthStatus.FAILING
        }


@pytest.mark.req("FR-21", "SEC-36")
def test_upkeep_round_writes_no_heartbeat_when_the_policy_cannot_be_read(gw, monkeypatch):
    def down(*args, **kwargs):
        raise OperationalError("SELECT", {}, Exception("gone"))

    monkeypatch.setattr("keepair.gateway.snapshot.load_snapshot", down)
    seen = gw.app.state.maintenance.tick()
    assert seen["policy_sync"] is False and seen["ledger"] is True
    with gw.engine.connect() as conn:
        health = {h.component.id: h.status for h in read_health(conn, gw.clock)}
    assert (
        health["policy_sync"] is HealthStatus.UNKNOWN and health["ledger"] is HealthStatus.HEALTHY
    )


@pytest.mark.req("FR-21", "SEC-36", "Hard rule 5")
def test_upkeep_round_reports_a_database_outage(settings, unreachable_engine):
    gw = make_gateway(settings, unreachable_engine)
    assert gw.app.state.maintenance.tick() == {
        "policy_sync": False,
        "ledger": False,
        "alerting": False,
        "gateway": False,
    }
    assert gw.metrics.value("keepair_failures_total", code="DATABASE_UNREACHABLE") == 1


def run_demo(settings, engine):
    with engine.begin() as conn:
        seed(conn, demo_clock())
        issue_demo_credentials(conn)
    gw = make_gateway(settings, engine)

    def send(item, headers, body):
        response = gw.client.post("/v1/chat/completions", headers=headers, json=body)
        return response.status_code, response.json()

    outcomes = run_plan(build_plan(), send)
    totals = gw.rows("SELECT sum(committed_micros), sum(reserved_micros) FROM budgets")[0]
    return gw, send, outcomes, tuple(totals)


@pytest.mark.req("Hard rule 2 (deterministic demo)", "FR-05", "UX-5")
def test_demo_traffic_gives_the_same_outcomes_on_every_run(settings, engine):
    plan = build_plan()
    assert len(plan) == TOTAL == 500 and plan == build_plan()
    gw, send, first, totals_first = run_demo(settings, engine)
    counts = Counter(first)
    assert sum(counts.values()) == 500
    for code in (
        "ALLOWED",
        "VENDOR_BLOCKED",
        "MODEL_BLOCKED",
        "UNKNOWN_MODEL",
        "BUDGET_EXHAUSTED",
        "APPROVAL_REQUIRED",
    ):
        assert counts[code] > 0, code
    assert counts["ALLOWED"] > 300 and 8 <= counts["APPROVAL_REQUIRED"] <= 12
    assert set(counts) <= {
        "ALLOWED",
        "VENDOR_BLOCKED",
        "MODEL_BLOCKED",
        "UNKNOWN_MODEL",
        "BUDGET_EXHAUSTED",
        "APPROVAL_REQUIRED",
    }
    assert len(gw.rows("SELECT 1 FROM gateway_decisions")) == 500
    assert gw.provider.call_count == counts["ALLOWED"]

    # Sending the same plan again replays stored results: no new spend, no provider call.
    assert run_plan(plan, send) == first
    assert (
        tuple(gw.rows("SELECT sum(committed_micros), sum(reserved_micros) FROM budgets")[0])
        == totals_first
    )
    assert gw.provider.call_count == counts["ALLOWED"]

    # A fresh seed and a fresh run give exactly the same decisions and the same totals.
    _, _, second, totals_second = run_demo(settings, engine)
    assert second == first and totals_second == totals_first
    # No hard-limit budget went over its cap.
    assert not gw.rows(
        "SELECT 1 FROM budgets WHERE policy IN ('HARD','APPROVAL') AND committed_micros + reserved_micros > cap_micros"
    )


@pytest.mark.req("v1.4 Section 2.4 (latency budget)", "ISO 25010 performance efficiency")
def test_gateway_overhead_is_measured(gw, record_property):
    """Evidence, not a pilot result: time added by the gateway with a zero-latency provider.

    The PRD target (p95 at most 25 ms before dispatch) is for a pilot deployment. This
    test runs on a shared CI machine, so it only fails on a gross regression.
    """
    import time  # test-only measurement

    gw.chat("Build Assistant")  # warm up
    samples = []
    for i in range(100):
        start = time.perf_counter()
        assert gw.chat("Ticket Triage", content=f"latency sample {i}").status_code == 200
        samples.append((time.perf_counter() - start) * 1000)
    samples.sort()
    p50, p95 = samples[49], samples[94]
    record_property("gateway_total_ms_p50", round(p50, 1))
    record_property("gateway_total_ms_p95", round(p95, 1))
    print(f"\ngateway round trip incl. reserve and settle: p50 {p50:.1f} ms, p95 {p95:.1f} ms")
    assert p95 < 500
