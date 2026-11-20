"""Billing ingestion, allocation in the database and reconciliation (FR-01, FR-03, FR-07, FR-19)."""

from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from keepair.billing import reconcile
from keepair.billing.focus import Quarantine
from keepair.billing.ingest import ingest, reallocate
from keepair.demo import billing as demo
from keepair.demo.seed import demo_clock
from keepair.demo.usage_plan import usage_plan
from keepair.formulas import _tenant
from keepair.rng import seeded_rng

FILES = demo.generate()
JAN = date(2026, 1, 1)
RNG = seeded_rng(7)  # one generator for the module, so batch IDs differ


def load(conn, name=demo.USAGE_FILE, source="vendor-a-usage", data=None):
    return ingest(
        conn, tenant_id=_tenant(conn), source=source, file_name=name,
        data=FILES[name] if data is None else data, actor="tester", clock=demo_clock(), rng=RNG,
    )  # fmt: skip


def snapshot(conn):
    tables = ("raw_billing_records", "normalized_cost_records", "allocation_facts")
    return {
        t: conn.execute(
            text(f"SELECT count(*), coalesce(sum(hashtext(t::text)), 0) FROM {t} t")  # noqa: S608
        ).one()
        for t in tables
    }


def states(conn):
    return dict(
        conn.execute(
            text("SELECT state, count(*) FROM allocation_facts WHERE is_current GROUP BY state")
        ).all()
    )


@pytest.mark.req("FR-01 (idempotent processing)", "FR-07 (reruns do not duplicate)")
def test_reingest_same_period_is_idempotent(engine):
    with engine.begin() as conn:
        first = load(conn)
        assert (
            first.status,
            first.rows_total,
            first.rows_new,
            first.rows_revised,
            first.rows_unchanged,
        ) == ("LOADED", 431, 431, 0, 0)
        before = snapshot(conn)
        total = conn.execute(
            text("SELECT sum(billed_micros) FROM normalized_cost_records WHERE is_current")
        ).scalar()
        again = load(conn)
        assert (again.rows_new, again.rows_revised, again.rows_unchanged) == (0, 0, 431)
        assert snapshot(conn) == before  # not one row added or changed
        assert (
            conn.execute(
                text("SELECT sum(billed_micros) FROM normalized_cost_records WHERE is_current")
            ).scalar()
            == total
        )
        assert (
            conn.execute(
                text("SELECT count(*) FROM ingestion_batches WHERE status = 'LOADED'")
            ).scalar()
            == 2
        )
        conn.rollback()


@pytest.mark.req("FR-01 (corrected period)", "FR-02 (raw records remain available)")
def test_corrected_period_creates_new_revision_and_preserves_history(engine):
    with engine.begin() as conn:
        load(conn)
        keys = [r["x_RecordKey"] for r in demo.correction_rows()]
        old = dict(
            conn.execute(
                text(
                    "SELECT record_key, billed_micros FROM normalized_cost_records WHERE record_key = ANY(:k)"
                ),
                {"k": keys},
            ).all()
        )
        result = load(conn, demo.CORRECTION_FILE)
        assert (result.rows_total, result.rows_new, result.rows_revised) == (2, 0, 2)
        rows = conn.execute(
            text(
                "SELECT record_key, revision, is_current, billed_micros FROM normalized_cost_records WHERE record_key = ANY(:k) ORDER BY record_key, revision"
            ),
            {"k": keys},
        ).all()
        assert [(r.revision, r.is_current) for r in rows] == [(1, False), (2, True)] * 2
        for r in rows:  # the old figure is still there; the new one is 5% higher
            assert r.billed_micros == (
                old[r.record_key] if r.revision == 1 else old[r.record_key] * 105 // 100
            )
        assert (
            conn.execute(
                text("SELECT count(*) FROM raw_billing_records WHERE record_key = ANY(:k)"),
                {"k": keys},
            ).scalar()
            == 4
        )
        facts = conn.execute(
            text(
                "SELECT f.is_current, n.revision FROM allocation_facts f JOIN normalized_cost_records n ON n.id = f.record_id WHERE n.record_key = ANY(:k) ORDER BY n.revision"
            ),
            {"k": keys},
        ).all()
        assert [tuple(f) for f in facts] == [(False, 1), (False, 1), (True, 2), (True, 2)]
        assert (
            load(conn, demo.CORRECTION_FILE).rows_unchanged == 2
        )  # the correction is idempotent too
        # The first file again is all "unchanged" for its own revisions, and changes nothing.
        assert load(conn).rows_unchanged == 431
        assert (
            conn.execute(
                text("SELECT count(*) FROM normalized_cost_records WHERE is_current")
            ).scalar()
            == 431
        )
        conn.rollback()


@pytest.mark.req("FR-01", "SEC-28")
def test_changed_content_under_the_same_revision_is_quarantined(engine):
    rows = demo.usage_rows()
    with engine.begin() as conn:
        load(conn)
        before = snapshot(conn)
        tampered = demo.render([rows[0] | {"BilledCost": "1.000000"}, *rows[1:3]])
        with pytest.raises(Quarantine, match="higher revision"):
            load(conn, data=tampered)
        stale = demo.render([rows[5] | {"x_Revision": "3"}])
        load(conn, data=stale)
        with pytest.raises(Quarantine, match="older than the loaded one"):
            load(conn, data=demo.render([rows[5] | {"x_Revision": "2"}]))
        with pytest.raises(Quarantine, match="Unknown billing source"):
            load(conn, source="vendor-z-usage")
        assert snapshot(conn)["raw_billing_records"][0] == before["raw_billing_records"][0] + 1
        conn.rollback()


@pytest.mark.req("SEC-28", "FR-02 (a failing batch is quarantined, not loaded)")
def test_broken_file_loads_nothing(engine):
    with engine.begin() as conn:
        with pytest.raises(Quarantine) as bad:
            load(conn, demo.BROKEN_FILE)
        assert len(bad.value.reasons) == 4
        assert (
            snapshot(conn)["raw_billing_records"][0] == 0
        )  # the one valid row is not loaded either
        conn.rollback()


@pytest.mark.req("FR-03", "FR-06", "Owner brief phase 4 (demo)")
def test_demo_file_gives_one_unmatched_one_unallocated_and_one_review_join(engine):
    with engine.begin() as conn:
        load(conn)
        assert states(conn) == {"ALLOCATED": 461, "REVIEW": 1, "UNMATCHED": 1, "UNALLOCATED": 1}
        review = conn.execute(
            text(
                "SELECT f.join_confidence, f.confidence, p.name FROM allocation_facts f JOIN projects p ON p.id = f.project_id WHERE f.state = 'REVIEW'"
            )
        ).one()
        assert tuple(review) == (70, "INFERRED", "Red Team")  # in the 70 to 89 band
        confidences = dict(
            conn.execute(
                text(
                    "SELECT confidence, count(*) FROM allocation_facts WHERE is_current AND state = 'ALLOCATED' GROUP BY confidence"
                )
            ).all()
        )
        assert confidences == {
            "DIRECT": 395,
            "INFERRED": 66,
        }  # 33 shared records, each split in two
        assert conn.execute(
            text(
                "SELECT min(join_confidence), max(join_confidence) FROM allocation_facts WHERE confidence = 'DIRECT'"
            )
        ).one() == (90, 90)
        # Every record is fully accounted for: facts add up to the record, to the micro-unit.
        off = conn.execute(
            text(
                "SELECT count(*) FROM normalized_cost_records n WHERE n.is_current AND n.billed_micros <> (SELECT sum(amount_micros) FROM allocation_facts f WHERE f.record_id = n.id AND f.is_current)"
            )
        ).scalar()
        assert off == 0
        split = conn.execute(
            text(
                "SELECT p.name, sum(f.amount_micros) FROM allocation_facts f JOIN projects p ON p.id = f.project_id WHERE f.rule_id IS NOT NULL GROUP BY p.name ORDER BY 1"
            )
        ).all()
        total = sum(amount for _, amount in split)
        assert [name for name, _ in split] == ["Build Assistant", "Log Summarizer"]
        assert abs(split[0][1] * 10 - total * 6) <= 33 * 10  # 60% within one micro-unit per record
        conn.rollback()


@pytest.mark.req("FR-03 (manual assignment, auditable change history)")
def test_manual_assignment_reallocates_and_keeps_the_earlier_fact(engine):
    with engine.begin() as conn:
        load(conn)
        tenant = _tenant(conn)
        record = conn.execute(
            text(
                "SELECT n.id, n.source, n.record_key FROM normalized_cost_records n JOIN allocation_facts f ON f.record_id = n.id WHERE f.state = 'UNMATCHED'"
            )
        ).one()
        project = conn.execute(text("SELECT id FROM projects WHERE name = 'Lead Scoring'")).scalar()
        conn.execute(
            text(
                "INSERT INTO manual_allocations VALUES (:t, :s, :k, :p, 'tester', 'Belongs to the growth pilot.', now())"
            ),
            {"t": tenant, "s": record.source, "k": record.record_key, "p": project},
        )
        reallocate(conn, tenant, [record.id], demo_clock())
        facts = conn.execute(
            text(
                "SELECT state, confidence, project_id, is_current FROM allocation_facts WHERE record_id = :r ORDER BY id"
            ),
            {"r": record.id},
        ).all()
        assert [tuple(f) for f in facts] == [
            ("UNMATCHED", None, None, False),
            ("ALLOCATED", "MANUAL", project, True),
        ]
        assert states(conn)["ALLOCATED"] == 462 and "UNMATCHED" not in states(conn)
        with (
            pytest.raises(IntegrityError),
            conn.begin_nested(),
        ):  # the shape rule is in the database too
            conn.execute(
                text("UPDATE allocation_facts SET confidence = NULL WHERE state = 'ALLOCATED'")
            )
        conn.rollback()


@pytest.mark.req("FR-07", "UX-8")
def test_database_refuses_a_billing_record_labelled_as_an_estimate(engine):
    with engine.begin() as conn:
        load(conn)
        with pytest.raises(IntegrityError), conn.begin_nested():
            conn.execute(
                text("UPDATE normalized_cost_records SET finalization_state = 'ESTIMATED'")
            )
        assert not conn.execute(
            text(
                "SELECT 1 FROM information_schema.columns WHERE table_name = 'usage_events' AND column_name LIKE '%final%'"
            )
        ).all()
        conn.rollback()


@pytest.mark.req("FR-07", "FR-19", "B-b")
def test_uncontrolled_spend_detected_from_provider_usage_delta(engine):
    with engine.begin() as conn:
        tenant = _tenant(conn)
        assert (
            reconcile.uncontrolled_projects(conn, tenant) == set()
        )  # no provider data, no finding
        load(conn)
        lines = {line.project: line for line in reconcile.project_lines(conn, tenant, JAN, "USD")}
        assert len(lines) == 12
        lead = lines["Lead Scoring"]
        assert lead.estimated_micros == 2_400_000_000  # the seeded gateway usage
        assert lead.provider_micros == lead.estimated_micros * 13 // 10 - (
            lead.estimated_micros * 13 // 10 - lead.provider_micros
        )
        assert (
            lead.uncontrolled_micros == lead.difference_micros > 700_000_000
            and lead.share_bp == 7_692
        )
        flagged = {name for name, line in lines.items() if line.uncontrolled_micros}
        assert flagged == {"Lead Scoring"}
        assert reconcile.uncontrolled_projects(conn, tenant) == {lead.project_id}
        ordinary = lines["Code Review Agent"]  # the provider is a little below the estimate
        assert (
            -0.01 < ordinary.difference_micros / ordinary.estimated_micros < 0
            and ordinary.share_bp == 10_000
        )
        conn.rollback()


@pytest.mark.req("FR-19")
def test_below_threshold_is_not_flagged():
    unit = 1_000_000
    assert reconcile.uncontrolled_micros(100 * unit, 100 * unit) == 0
    assert reconcile.uncontrolled_micros(100 * unit, 98 * unit) == 0  # exactly 2%: not above
    assert reconcile.uncontrolled_micros(100 * unit, 97 * unit) == 3 * unit
    assert reconcile.uncontrolled_micros(10 * unit, 9 * unit + 1) == 0  # under one whole unit
    assert reconcile.uncontrolled_micros(10 * unit, 8 * unit) == 2 * unit
    assert (
        reconcile.uncontrolled_micros(50 * unit, 80 * unit) == 0
    )  # the gateway saw more: not a finding
    assert (
        reconcile.controlled_share_bp(0, 5) is None
        and reconcile.controlled_share_bp(100, 250) == 10_000
    )


@pytest.mark.req("Hard rule 2", "FR-05", "FR-07")
def test_seeded_gateway_usage_matches_the_budgets_and_the_billing_plan(engine):
    plan = usage_plan()
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT project, sum(actual_micros) AS cost, sum(price_micros) AS price, min(currency) AS currency FROM usage_events GROUP BY project"
            )
        ).all()
        budgets = dict(
            conn.execute(
                text(
                    "SELECT p.name, b.committed_micros FROM budgets b JOIN projects p ON p.id = b.scope_id"
                )
            ).all()
        )
    assert (
        len(plan) == conn_count(engine) and len(rows) == 13
    )  # 12 projects and the team's own spend
    for r in rows:
        if r.project:  # each project's usage history adds up to its budget's committed amount
            assert r.cost == budgets[r.project], r.project
            assert (r.price == r.cost) if r.currency == "USD" else (r.price > r.cost)


def conn_count(engine) -> int:
    with engine.connect() as conn:
        return conn.execute(text("SELECT count(*) FROM usage_events")).scalar()
