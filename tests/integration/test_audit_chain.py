"""The audit record: hash chain, tamper evidence, and the restricted database role (phase 6)."""

from itertools import pairwise

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from keepair import audit
from keepair.demo.seed import demo_clock
from keepair.demo.tamper import NEW_REASON, tamper
from keepair.schema import audit_head, audit_log
from tests.gateway_harness import make_gateway
from tests.system.conftest import make_ui, upload

pytestmark = pytest.mark.req("SEC-32", "FR-12 (audit log)")

OFF = "ALTER TABLE audit_log DISABLE TRIGGER audit_log_no_change"
ON = "ALTER TABLE audit_log ENABLE TRIGGER audit_log_no_change"


def verify(engine) -> audit.VerifyResult:
    with engine.connect() as conn:
        return audit.verify(conn)


def as_owner(engine, statement: str, **params) -> None:
    """What only the owner of the table can do: switch the trigger off for one statement."""
    with engine.begin() as conn:
        conn.execute(text(OFF))
        conn.execute(text(statement), params)
        conn.execute(text(ON))


def append(engine, action="test.action") -> int:
    with engine.begin() as conn:
        return audit.record(
            conn, demo_clock(), tenant_id=None, actor="tester", action=action,
            subject_type="thing", subject_id="1", after={"n": 1}, reason="A test record.",
        )  # fmt: skip


def test_seeded_chain_verifies_and_links_from_the_genesis_hash(engine):
    result = verify(engine)
    assert result.ok and result.checked == 8 and result.broken_at is None
    with engine.connect() as conn:
        rows = conn.execute(select(audit_log).order_by(audit_log.c.seq)).all()
        head = conn.execute(select(audit_head)).one()
    assert [r.seq for r in rows] == list(range(1, 9))
    assert bytes(rows[0].prev_hash) == audit.GENESIS
    for earlier, later in pairwise(rows):
        assert bytes(later.prev_hash) == bytes(earlier.row_hash)
    assert (
        (head.seq, bytes(head.row_hash)) == (8, bytes(rows[-1].row_hash)) == (8, result.head_hash)
    )
    assert append(engine) == 9 and verify(engine).checked == 9


def test_audit_hash_chain_detects_tampering(engine):
    """Brief, phase 6: hash chain detects tampering. A changed record."""
    with engine.begin() as conn:
        seq = tamper(conn)
    result = verify(engine)
    assert not result.ok and result.broken_at == seq == 8 and result.checked == 7
    assert "changed after it was written" in result.problem
    with engine.connect() as conn:
        assert conn.execute(
            select(audit_log.c.reason).where(audit_log.c.seq == seq)
        ).scalar_one() == NEW_REASON  # fmt: skip


@pytest.mark.parametrize("column", ["actor", "action", "subject_id", "occurred_at", "after"])
def test_every_recorded_field_is_covered_by_the_hash(engine, column):
    value = {"occurred_at": "now()", "after": '\'{"status": "ALLOWED"}\'::jsonb'}.get(
        column, "'changed'"
    )
    as_owner(engine, f"UPDATE audit_log SET {column} = {value} WHERE seq = 3")  # noqa: S608
    result = verify(engine)
    assert not result.ok and result.broken_at == 3 and result.checked == 2


def test_a_removed_record_is_detected(engine):
    as_owner(engine, "DELETE FROM audit_log WHERE seq = 4")
    result = verify(engine)
    assert not result.ok and result.broken_at == 4 and "missing" in result.problem


def test_removed_newest_records_are_detected_through_the_head(engine):
    as_owner(engine, "DELETE FROM audit_log WHERE seq >= 7")
    result = verify(engine)
    assert not result.ok and result.broken_at == 7 and result.checked == 6
    assert "shorter than its head" in result.problem


def test_a_record_inserted_with_a_made_up_hash_is_detected(engine):
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO audit_log (seq, occurred_at, actor, action, subject_type, subject_id,"
                " prev_hash, row_hash) VALUES (9, now(), 'intruder', 'budget.policy_changed',"
                " 'budget', 'x', decode(repeat('ab', 32), 'hex'), decode(repeat('cd', 32), 'hex'))"
            )
        )
    result = verify(engine)
    assert not result.ok and result.broken_at == 9 and "does not follow" in result.problem


def test_a_rewritten_tail_with_consistent_hashes_still_fails_at_the_head(engine):
    """Someone recomputes the last record's hash after editing it, but cannot also be
    consistent with the stored head unless they rewrite that too (see module docstring)."""
    as_owner(
        engine,
        "UPDATE audit_log SET reason = 'x', row_hash = decode(repeat('ef', 32), 'hex') "
        "WHERE seq = 8",
    )
    assert not verify(engine).ok


# --- The application role (brief, phase 6) ---------------------------------------------


def test_app_role_cannot_update_or_delete_audit_rows(app_engine):
    for statement in (
        "UPDATE audit_log SET reason = 'x' WHERE seq = 1",
        "DELETE FROM audit_log WHERE seq = 1",
        "TRUNCATE audit_log",
        "DELETE FROM audit_head",
        "INSERT INTO audit_head (id, seq, row_hash) VALUES (1, 0, decode(repeat('00', 32), 'hex'))",
        "ALTER TABLE audit_log DISABLE TRIGGER audit_log_no_change",
        "DROP TABLE audit_log",
    ):
        with pytest.raises(ProgrammingError, match=r"permission denied|must be owner"):
            with app_engine.begin() as conn:
                conn.execute(text(statement))
    with app_engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(audit_log)).scalar_one() == 8
    assert append(app_engine) == 9  # it may read and append, and nothing else
    assert verify(app_engine).ok


def test_trigger_refuses_changes_even_for_a_role_with_the_privilege(engine):
    """Defence in depth: the superuser of the test database holds UPDATE and is refused."""
    for statement in ("UPDATE audit_log SET reason = 'x' WHERE seq = 1",
                      "DELETE FROM audit_log WHERE seq = 1"):  # fmt: skip
        with pytest.raises(DBAPIError, match="AUDIT_IMMUTABLE"):
            with engine.begin() as conn:
                conn.execute(text(statement))
    assert verify(engine).ok


@pytest.mark.req("SEC-14", "A.8.2 (least privilege)")
def test_the_services_work_under_the_restricted_role(settings, app_engine):
    """The UI and the gateway run as keepair_app in the demo stack. Everything they do
    must work with that role's grants."""
    gw = make_gateway(settings, app_engine)
    assert gw.chat("Ticket Triage").status_code == 200
    assert gw.chat("Ticket Triage", "vb-large").status_code == 403
    assert gw.chat("Research Agent").status_code == 202
    assert all(gw.app.state.maintenance.tick().values())
    ui = make_ui(settings, app_engine, gateway_client=gw.client)
    assert upload(ui, "vendor-a-usage-2026-01.csv").status_code == 303
    blocked = ui.post(
        "/gateway/block",
        {"type": "model", "id": "vendor-a/model-2", "reason": "Checked under the app role.",
         "totp": ui.code()},
    )  # fmt: skip
    assert blocked.status_code == 303
    [held] = ui.soup("/approvals").select("tr[data-held]")
    assert (
        ui.post(f"/approvals/held/{held['data-held']}", {"decision": "approve"}).status_code == 303
    )
    assert ui.post("/audit-log/verify").status_code == 200
    for path in ("/", "/spend", "/budgets", "/gateway", "/reports", "/admin", "/audit-log"):
        assert ui.client.get(path).status_code == 200
    assert ui.client.get("/reports/showback.csv").status_code == 200


@pytest.mark.req("SEC-32 (daily verifier)", "FR-21", "Hard rule 5")
def test_gateway_upkeep_verifies_the_chain_at_start_and_daily(settings, engine):
    from datetime import timedelta

    from keepair.failures import FAILURES_TOTAL

    gw = make_gateway(settings, engine)
    upkeep = gw.app.state.maintenance
    upkeep.tick()  # at start: the seeded chain is intact
    assert gw.metrics.value(FAILURES_TOTAL, code="AUDIT_CHAIN_BROKEN") == 0
    with engine.begin() as conn:
        tamper(conn)
    upkeep.tick()  # not due again yet
    assert gw.metrics.value(FAILURES_TOTAL, code="AUDIT_CHAIN_BROKEN") == 0
    gw.clock.advance(timedelta(hours=24))
    upkeep.tick()
    assert gw.metrics.value(FAILURES_TOTAL, code="AUDIT_CHAIN_BROKEN") == 1
    [alert] = gw.rows("SELECT severity, message FROM alerts WHERE code = 'AUDIT_CHAIN_BROKEN'")
    assert alert.severity == "SEV1" and "record 8" in alert.message
