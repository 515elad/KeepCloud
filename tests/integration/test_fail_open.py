"""Fail-open through the encrypted spool, and its limits (SEC-06, SD-04 default, B-m).

Two kinds of outage are injected:
- ``fault``: ledger writes fail while reads still work (the demo console's switch);
- ``outage``: every database call fails, as when PostgreSQL is stopped.
"""

import base64
import uuid
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError

from keepair.demo.seed import demo_clock, demo_token
from keepair.gateway.adapters import NoReservation, SpoolPermit
from keepair.gateway.spool import Caps, Spool, SpoolError, SpoolFull, load_key
from keepair.rng import seeded_rng
from tests.gateway_harness import make_gateway

SOFT, MONITOR, HARD, APPROVAL = "Ticket Triage", "Reply Drafts", "Build Assistant", "Research Agent"
SOFT_UNDER_HARD = "Log Summarizer"  # soft project, but its team and department are hard limits
SOFT_PATH = ["Ticket Triage", "Support Automation", "Customer Operations", "Northwind Labs"]


def fault(gw, active=True):
    gw.app.state.ledger_state.set_fault(active)


def committed(gw, names=SOFT_PATH):
    return {n: gw.budget(n).committed_micros for n in names}


def restore(gw):
    fault(gw, False)
    return gw.app.state.maintenance.tick()


@pytest.mark.req("SEC-06", "FR-05", "FR-12", "B-m")
def test_fail_open_is_counted_alerted_and_audited(gw):
    before = committed(gw)
    fault(gw)
    response = gw.chat(SOFT, content="while the ledger is down")
    assert response.status_code == 200 and response.headers["x-keepair-decision"] == "FAIL_OPEN"
    assert "x-keepair-reservation-id" not in response.headers
    request_id = response.headers["x-keepair-request-id"]

    # Counted and alerted while it happens. Nothing is in the ledger yet.
    assert gw.metrics.value("keepair_fail_open_total") == 1
    assert gw.metrics.value("keepair_failures_total", code="FAIL_OPEN") == 1
    assert gw.rows("SELECT 1 FROM alerts WHERE code = 'FAIL_OPEN'")  # alerting itself still works
    assert committed(gw) == before and not gw.rows("SELECT 1 FROM fail_events")
    status = gw.client.get("/status").json()
    assert status["ledger"] == {
        "reachable": False,
        "down_since": "2026-01-15T09:00:00Z",
        "simulated_fault": True,
    }
    assert status["spool"]["waiting_requests"] == 1

    # Ledger back: the record is replayed into every table that should know about it.
    restore(gw)
    [event] = gw.rows("SELECT * FROM fail_events")
    assert str(event.id) == request_id and event.kind == "FAIL_OPEN" and event.usage_known
    assert (event.agent, event.project, event.model_id) == (
        "ticket-triage-agent",
        "Ticket Triage",
        "vendor-a/model-1",
    )
    assert event.budget_id == gw.budget(SOFT).id and event.detail["reconciled"] is True
    assert event.acknowledged_at is None and event.amount_micros > 0
    after = committed(gw)
    for name in SOFT_PATH:  # the spend lands on the whole limit path, once
        assert after[name] == before[name] + event.amount_micros
    [decision] = gw.rows("SELECT * FROM gateway_decisions WHERE id = :id", id=request_id)
    assert (decision.outcome, decision.reason_code, decision.http_status) == (
        "ALLOWED",
        "FAIL_OPEN",
        200,
    )
    [usage] = gw.rows("SELECT * FROM usage_events")
    assert (usage.project, usage.actual_micros, usage.usage_known) == (
        "Ticket Triage",
        event.amount_micros,
        True,
    )
    assert gw.client.get("/status").json()["spool"]["waiting"] == 0
    assert gw.chat(SOFT).headers["x-keepair-decision"] == "RESERVED"  # back to normal


@pytest.mark.req("SEC-06 (blocks and hard limits fail closed)", "D-01", "SD-04", "Hard rule 7")
def test_ledger_down_denies_hard_approval_and_every_block(gw):
    gw.chat(HARD), gw.chat(APPROVAL)  # seen before the outage
    before = committed(
        gw, ["Build Assistant", "Research Agent", "Log Summarizer", "Platform", "Engineering"]
    )
    fault(gw)
    calls = gw.provider.call_count
    for project in (HARD, APPROVAL, SOFT_UNDER_HARD):
        response = gw.chat(project)
        assert response.status_code == 403, project
        assert response.json()["error"] == {
            "type": "keepair_policy_denied", "code": "BUDGET_FAIL_CLOSED",
            "request_id": response.headers["x-keepair-request-id"],
        }  # fmt: skip
    # Blocks are decided before the ledger is touched: fail-open never reaches them.
    for model, code in (("vb-large", "VENDOR_BLOCKED"), ("vendor-a/model-3", "MODEL_BLOCKED"),
                        ("vendor-a/model-9", "UNKNOWN_MODEL")):  # fmt: skip
        for project in (SOFT, MONITOR):
            assert gw.chat(project, model).json()["error"]["code"] == code
    assert gw.provider.call_count == calls and gw.metrics.value("keepair_fail_open_total") == 0
    assert gw.chat(MONITOR).headers["x-keepair-decision"] == "FAIL_OPEN"  # monitor continues
    restore(gw)
    assert committed(gw, list(before)) == before  # nothing was spent on the refused budgets
    reasons = [
        r.reason_code
        for r in gw.rows("SELECT reason_code FROM gateway_decisions WHERE outcome = 'DENIED'")
    ]
    assert sorted(reasons) == sorted(
        ["BUDGET_FAIL_CLOSED"] * 3 + ["VENDOR_BLOCKED", "MODEL_BLOCKED", "UNKNOWN_MODEL"] * 2
    )
    assert not gw.rows("SELECT 1 FROM fail_events WHERE project <> 'Reply Drafts'")


@pytest.mark.req("SEC-09", "FR-18 (blocks never fail open)")
def test_stale_policy_during_an_outage_stops_fail_open_too(gw, monkeypatch):
    fault(gw)
    assert gw.chat(SOFT).status_code == 200

    def down(*args, **kwargs):
        raise OperationalError("SELECT", {}, Exception("gone"))

    monkeypatch.setattr("keepair.gateway.snapshot.load_snapshot", down)
    gw.clock.advance(timedelta(seconds=31))
    response = gw.chat(SOFT)  # a block added since the snapshot could not be seen
    assert response.status_code == 403 and response.json()["error"]["code"] == "SNAPSHOT_STALE"
    assert gw.provider.call_count == 1


@pytest.mark.req("SEC-06 (spool cap)", "SD-04")
def test_spool_full_denies(settings, engine):
    gw = make_gateway(settings, engine, spool_caps=Caps(max_records=3))
    fault(gw)
    statuses = [gw.chat(SOFT).status_code for _ in range(5)]
    assert statuses == [200, 200, 200, 503, 503]
    full = gw.chat(MONITOR)
    assert full.json()["error"]["code"] == "FAIL_OPEN_CAPACITY" and gw.provider.call_count == 3
    assert gw.metrics.value("keepair_failures_total", code="SPOOL_FULL") == 3
    restore(gw)  # replay empties the spool
    fault(gw)
    assert gw.chat(SOFT).status_code == 200
    assert len(gw.rows("SELECT 1 FROM fail_events")) == 3


@pytest.mark.req("SEC-06 (capped window)", "SD-04")
def test_fail_open_window_is_capped_by_time_and_size(settings, engine):
    gw = make_gateway(settings, engine, spool_caps=Caps(max_age_s=3600))
    fault(gw)
    assert gw.chat(SOFT).status_code == 200
    gw.clock.advance(timedelta(seconds=10))  # keep the policy snapshot fresh
    gw.clock.advance(timedelta(seconds=3590))
    gw.app.state.snapshots.refresh(gw.rows("SELECT id FROM tenants")[0].id)
    assert gw.chat(SOFT).status_code == 200  # 60 minutes after the first record: still inside
    gw.clock.advance(timedelta(seconds=2))
    gw.app.state.snapshots.refresh(gw.rows("SELECT id FROM tenants")[0].id)
    assert gw.chat(SOFT).json()["error"]["code"] == "FAIL_OPEN_CAPACITY"  # the hour is used up
    small = make_gateway(settings, engine, spool_caps=Caps(max_bytes=1))
    fault(small)
    assert small.chat(SOFT).status_code == 200  # the first record fits an empty spool
    assert small.chat(SOFT).json()["error"]["code"] == "FAIL_OPEN_CAPACITY"


@pytest.mark.req("SEC-06 (no record, no dispatch)", "S-34")
def test_spool_write_failure_denies(gw, monkeypatch):
    fault(gw)

    def disk_error(*args, **kwargs):
        raise OSError("No space left on device")

    monkeypatch.setattr("os.fsync", disk_error)
    response = gw.chat(SOFT)
    assert response.status_code == 503 and response.json()["error"]["code"] == "FAIL_OPEN_CAPACITY"
    assert not gw.provider.called
    assert gw.metrics.value("keepair_failures_total", code="SPOOL_WRITE_FAILED") == 1
    assert gw.metrics.value("keepair_fail_open_total") == 0


@pytest.mark.req("SEC-06 (replay)", "FR-07 (reruns do not duplicate)")
def test_replay_is_idempotent(gw, monkeypatch):
    from keepair.gateway import replay as replay_module

    before = committed(gw)
    fault(gw)
    for i in range(4):
        assert gw.chat(SOFT, content=f"request {i}").status_code == 200
    spool = gw.app.state.spool
    entries = spool.pending()
    assert len(entries) == 4

    # A crash after the database commit but before the spool is marked: replay runs again.
    marks = []
    monkeypatch.setattr(spool, "mark_replayed", lambda record_id: marks.append(record_id))
    monkeypatch.setattr(spool, "compact", lambda: False)
    fault(gw, False)
    assert replay_module.replay(gw.engine, spool, gw.clock, seeded_rng(1)) == 4
    after_first = committed(gw)
    assert after_first != before and len(marks) == 4
    assert replay_module.replay(gw.engine, spool, gw.clock, seeded_rng(2)) == 0  # nothing new
    monkeypatch.undo()
    assert replay_module.replay(gw.engine, spool, gw.clock, seeded_rng(3)) == 0
    assert committed(gw) == after_first
    counts = gw.rows(
        "SELECT (SELECT count(*) FROM fail_events), (SELECT count(*) FROM usage_events), (SELECT count(*) FROM gateway_decisions)"
    )[0]
    assert tuple(counts) == (4, 4, 4)
    total = gw.rows("SELECT sum(amount_micros) FROM fail_events")[0][0]
    assert after_first["Ticket Triage"] - before["Ticket Triage"] == total
    assert spool.stats().waiting == 0 and spool.stats().bytes == 0  # the file was emptied


@pytest.mark.req("SEC-06 (replay after a crash)", "B-j")
def test_spooled_request_without_an_answer_is_replayed_at_its_estimate(
    settings, engine, tmp_path, monkeypatch
):
    """The gateway died after dispatch: a new process finds the open record and replays it."""
    key = base64.b64encode(b"k" * 32).decode()
    gw = make_gateway(settings, engine, spool_dir=tmp_path, spool_key=key)
    fault(gw)

    class Killed(BaseException):
        """Stands for the process dying: not an error the code may handle."""

    def die(*args, **kwargs):
        gw.app.state.spool.claim(args[0].record_id)  # the adapter got as far as claiming
        raise Killed

    monkeypatch.setattr(gw.gateway.adapter, "dispatch", die)
    with pytest.raises(Killed):
        gw.gateway.handle_chat(
            authorization=f"Bearer {demo_token('ticket-triage-agent')}",
            headers={"idempotency-key": "crash-1"},
            raw_body=b'{"model":"model-1","messages":[{"role":"user","content":"x"}],"max_tokens":64}',
        )
    before = committed(gw)
    restarted = make_gateway(settings, engine, spool_dir=tmp_path, spool_key=key)
    assert restarted.app.state.spool.stats().waiting_usage == 1
    restarted.app.state.maintenance.tick()
    [event] = restarted.rows("SELECT amount_micros, usage_known, detail FROM fail_events")
    assert event.usage_known is False and event.detail["answered"] is False
    assert event.amount_micros == event.detail["estimate_micros"] > 0
    assert committed(restarted)["Ticket Triage"] == before["Ticket Triage"] + event.amount_micros


@pytest.mark.req("SEC-06", "FR-05 (settle)")
def test_provider_failures_in_fail_open_are_recorded(gw):
    fault(gw)
    gw.provider.mock(side_effect=httpx.ReadTimeout("boom"))
    assert gw.chat(SOFT).status_code == 504
    gw.provider.mock(return_value=httpx.Response(500, json={"error": "x"}))
    assert gw.chat(SOFT).status_code == 502
    restore(gw)
    rows = gw.rows(
        "SELECT amount_micros, usage_known, detail FROM fail_events ORDER BY amount_micros DESC"
    )
    assert (
        rows[0].usage_known is False and rows[0].amount_micros == rows[0].detail["estimate_micros"]
    )
    assert rows[1].amount_micros == 0  # the provider refused: nothing was spent


@pytest.mark.req("Hard rule 6", "SEC-01")
def test_adapter_refuses_without_an_open_spool_record(gw):
    from tests.integration.test_gateway_bypass import BODY

    adapter, spool = gw.gateway.adapter, gw.app.state.spool
    tenant = gw.rows("SELECT id FROM tenants")[0].id

    def send(permit):
        return adapter.dispatch(permit, tenant_id=tenant, vendor_id="vendor-a",
                                base_url="http://mock-provider:8090", body=BODY)  # fmt: skip

    for permit in (SpoolPermit("made-up"), SpoolPermit(str(uuid.uuid4()))):
        with pytest.raises(NoReservation):
            send(permit)
    spool.add_denial(
        "d-1", {"tenant_id": str(tenant), "agent_id": "a", "reason": "X", "status": 403}
    )
    with pytest.raises(NoReservation):
        send(SpoolPermit("d-1"))  # a refusal record is not a permit
    assert not gw.provider.called
    spool.open_record("r-1", {"agent_id": "a", "idempotency_key": "k"})
    assert send(SpoolPermit("r-1")).status == 200
    with pytest.raises(NoReservation):
        send(SpoolPermit("r-1"))  # once only
    assert gw.provider.call_count == 1


@pytest.mark.req("SEC-12 (revoked within 30 s)", "SEC-06")
def test_real_database_outage_accepts_recent_credentials_for_30_seconds_only(
    settings, engine, monkeypatch
):
    gw = make_gateway(settings, engine)
    assert gw.chat(SOFT).status_code == 200  # seen while the database was up
    broken = create_engine(
        "postgresql+psycopg://nobody@127.0.0.1:1/none", connect_args={"connect_timeout": 1}
    )
    monkeypatch.setattr(gw.gateway, "engine", broken)  # PostgreSQL is gone

    during = gw.chat(SOFT)
    assert during.status_code == 200 and during.headers["x-keepair-decision"] == "FAIL_OPEN"
    assert gw.chat(MONITOR).status_code == 503  # never seen: cannot be verified
    assert (
        gw.chat(SOFT, token="kair_" + "0" * 43 + "_000000").status_code == 401
    )  # malformed stays 401
    gw.clock.advance(timedelta(seconds=25))
    assert gw.chat(SOFT).status_code == 200
    gw.clock.advance(timedelta(seconds=10))  # 35 s after it was last verified
    late = gw.chat(SOFT)
    assert late.status_code == 503 and late.json()["error"]["code"] == "LEDGER_UNAVAILABLE"
    assert gw.provider.call_count == 3
    broken.dispose()


@pytest.mark.req("SEC-12 (revocation)", "B-c")
def test_cached_credentials_are_never_used_while_the_database_is_up(gw):
    assert gw.chat(SOFT).status_code == 200
    gw.execute(
        "UPDATE gateway_credentials SET revoked_at = now() WHERE agent_id = (SELECT id FROM agents WHERE name = 'ticket-triage-agent')"
    )
    assert gw.chat(SOFT).status_code == 401
    fault(gw)  # writes fail, reads work: the revocation is still seen
    assert gw.chat(SOFT).status_code == 401


@pytest.mark.req("FR-05 (idempotency)", "SEC-06")
def test_same_key_is_not_sent_twice_during_an_outage(gw):
    fault(gw)
    assert gw.chat(SOFT, key="once").status_code == 200
    again = gw.chat(SOFT, key="once")
    assert again.status_code == 409 and again.json()["error"]["code"] == "IDEMPOTENCY_IN_FLIGHT"
    assert gw.provider.call_count == 1


@pytest.mark.req("FR-21 (fail-open over 15 min is SEV2)", "SEC-36")
def test_prolonged_fail_open_escalates(gw):
    fault(gw)
    gw.app.state.maintenance.tick()
    assert gw.metrics.value("keepair_failures_total", code="FAIL_OPEN_PROLONGED") == 0
    gw.clock.advance(timedelta(minutes=15, seconds=1))
    gw.app.state.maintenance.tick()
    assert gw.metrics.value("keepair_failures_total", code="FAIL_OPEN_PROLONGED") == 1
    [alert] = gw.rows("SELECT severity FROM alerts WHERE code = 'FAIL_OPEN_PROLONGED'")
    assert alert.severity == "SEV2"
    # While the ledger is down its heartbeat stops; the others continue.
    seen = gw.app.state.maintenance.tick()
    assert seen["ledger"] is False and seen["gateway"] is True and seen["policy_sync"] is True


# --- the spool itself -------------------------------------------------------


def new_spool(tmp_path, key=b"k" * 32, caps=None, clock=None):
    return Spool(tmp_path, key, clock or demo_clock(), seeded_rng(1), caps)


@pytest.mark.req("SEC-06 (encrypted spool)", "SEC-25 (minimization)")
def test_spool_file_is_encrypted_and_holds_no_prompt(gw):
    fault(gw)
    gw.chat(SOFT, content="CANARY-PROMPT-51c2")
    raw = (gw.app.state.spool._path).read_bytes()
    assert len(raw) > 100
    for plain in (
        b"CANARY",
        b"ticket-triage",
        b"Ticket Triage",
        b"vendor-a",
        b"tenant_id",
        b"estimate",
    ):
        assert plain not in raw and plain not in base64.b64decode(raw.splitlines()[0])
    data = gw.app.state.spool.pending()[0].data
    assert "CANARY" not in str(data) and "messages" not in data  # metadata only


@pytest.mark.req("SEC-06", "SEC-36")
def test_tampered_or_foreign_spool_lines_are_detected_and_never_trusted(settings, engine, tmp_path):
    spool = new_spool(tmp_path)
    spool.open_record("r-1", {"agent_id": "a"})
    spool.open_record("r-2", {"agent_id": "a"})
    path = tmp_path / "fail-open.spool"
    lines = path.read_bytes().splitlines()
    flipped = bytearray(base64.b64decode(lines[0]))
    flipped[20] ^= 1
    path.write_bytes(base64.b64encode(bytes(flipped)) + b"\n" + lines[1] + b"\nnot-base64!\n")
    reloaded = new_spool(tmp_path)
    assert reloaded.corrupt_lines == 2 and [e.id for e in reloaded.pending()] == ["r-2"]
    assert new_spool(tmp_path, key=b"x" * 32).corrupt_lines == 3  # another key reads nothing

    gw = make_gateway(
        settings, engine, spool_dir=tmp_path, spool_key=base64.b64encode(b"x" * 32).decode()
    )
    gw.app.state.maintenance.tick()
    assert gw.metrics.value("keepair_failures_total", code="SPOOL_CORRUPT") == 1
    assert gw.client.get("/status").json()["spool"]["unreadable_lines"] == 3
    assert not gw.rows("SELECT 1 FROM fail_events")


@pytest.mark.req("SEC-06")
def test_spool_survives_a_restart_and_keeps_its_state(tmp_path):
    spool = new_spool(tmp_path)
    spool.open_record("r-1", {"agent_id": "a", "idempotency_key": "k1"})
    assert spool.claim("r-1") and not spool.claim("r-1")
    spool.complete("r-1", {"actual_micros": 5, "usage_known": True})
    spool.open_record("r-2", {"agent_id": "a"})
    spool.mark_replayed("r-1")
    again = new_spool(tmp_path)
    assert [e.id for e in again.pending()] == ["r-2"] and again.has_key("a", "k1")
    assert not again.compact()  # something is still waiting
    again.mark_replayed("r-2")
    assert again.compact() and (tmp_path / "fail-open.spool").read_bytes() == b""


@pytest.mark.req("SEC-06 (cap)")
def test_spool_caps(tmp_path):
    clock = demo_clock()
    spool = new_spool(tmp_path, caps=Caps(max_records=2, max_age_s=60), clock=clock)
    spool.open_record("r-1", {"agent_id": "a"})
    spool.add_denial("d-1", {"agent_id": "a"})
    with pytest.raises(SpoolFull):
        spool.open_record("r-2", {"agent_id": "a"})
    spool.mark_replayed("d-1")
    clock.advance(timedelta(seconds=61))
    with pytest.raises(SpoolFull, match="window"):
        spool.open_record("r-3", {"agent_id": "a"})


@pytest.mark.req("SEC-23", "SEC-21 (key handling)")
def test_spool_key_rules():
    key, ephemeral = load_key(None, "demo", seeded_rng(1))
    assert len(key) == 32 and ephemeral
    assert load_key(base64.b64encode(b"k" * 32).decode(), "prod", seeded_rng(1)) == (
        b"k" * 32,
        False,
    )
    with pytest.raises(ValueError, match="required in production"):
        load_key(None, "prod", seeded_rng(1))
    with pytest.raises(ValueError, match="32 bytes"):
        load_key(base64.b64encode(b"short").decode(), "demo", seeded_rng(1))
    with pytest.raises(SpoolError):
        Spool("/proc/keepair-nope", key, demo_clock(), seeded_rng(1)).open_record(
            "r", {"agent_id": "a"}
        )
