"""The seeded demo data matches the owner brief and is internally consistent."""

import re

import pytest
from sqlalchemy import func, select

from keepair import budgets as B
from keepair.demo.seed import demo_clock
from keepair.formulas import _tenant
from keepair.registry import DenyReason, RegistryError, add_block, decide_block, load_snapshot
from keepair.schema import (
    budgets,
    models,
    org_units,
    projects,
    registry_changes,
    unregistered_models,
    vendors,
)


@pytest.mark.req("Hard rule 2 (demo data)", "FR-04", "FR-18")
def test_demo_data_has_the_shape_in_the_brief(engine):
    with engine.connect() as conn:
        kinds = dict(
            conn.execute(select(org_units.c.kind, func.count()).group_by(org_units.c.kind)).all()
        )
        assert kinds == {"ORG": 1, "DEPT": 3, "TEAM": 6}
        assert conn.execute(select(func.count()).select_from(projects)).scalar_one() == 12
        assert conn.execute(select(func.count()).select_from(budgets)).scalar_one() == 22
        assert dict(conn.execute(select(vendors.c.id, vendors.c.status)).all()) == {
            "vendor-a": "ALLOWED",
            "vendor-b": "BLOCKED",
        }
        assert conn.execute(select(func.count()).select_from(models)).scalar_one() == 5
        assert conn.execute(select(unregistered_models.c.requested_name)).scalars().all() == [
            "vendor-a/model-9"
        ]
        assert set(conn.execute(select(budgets.c.currency)).scalars()) == {"USD", "EUR"}
        assert set(conn.execute(select(budgets.c.policy)).scalars()) == {
            "MONITOR",
            "SOFT",
            "HARD",
            "APPROVAL",
        }
        assert set(conn.execute(select(budgets.c.mode)).scalars()) == {"INDEPENDENT", "SUBDIVISION"}
        assert set(conn.execute(select(projects.c.key_custody)).scalars()) == {"KEEPAIR"}
        # Only fictional vendor names appear anywhere in the registry.
        assert all(
            m.startswith(("vendor-a/", "vendor-b/"))
            for m in conn.execute(select(models.c.id)).scalars()
        )


@pytest.mark.req("FR-04")
def test_demo_budgets_are_consistent(engine):
    with engine.connect() as conn:
        all_budgets = B.load_budgets(conn, _tenant(conn))
    assert B.currency_mismatches(all_budgets) == []
    for b in all_budgets.values():
        kids = [c for c in all_budgets.values() if c.parent_id == b.id and c.mode == "SUBDIVISION"]
        # Spend on a subdivision is also recorded on its parent.
        assert b.committed_micros >= sum(c.committed_micros for c in kids)
        assert b.reserved_micros >= sum(c.reserved_micros for c in kids)
        if b.enforcing:
            assert B.remaining(b) >= 0
        eff = B.effective_remaining(b, all_budgets).amount_micros
        assert eff is None or eff >= 0
    # The demo shows each situation the UI must explain.
    assert any(B.remaining(b) < 0 for b in all_budgets.values())  # over cap (monitor only)
    assert any(B.subdivision_overcommit(b, all_budgets) for b in all_budgets.values())
    assert any(
        (e := B.effective_remaining(b, all_budgets)).binding and e.binding.id != b.id
        for b in all_budgets.values()
    )
    reached = {
        t for b in all_budgets.values() for t in B.TICKS_PCT if B.usage(b).used_bp >= t * 100
    }
    assert reached == {50, 80, 90, 100}


@pytest.mark.req("FR-18", "SEC-05")
def test_block_decisions_on_the_demo_registry(engine):
    with engine.connect() as conn:
        snap = load_snapshot(conn, _tenant(conn))
    expected = {
        "vendor-a/model-1": None,
        "MODEL-1": None,
        " va-fast ": None,
        "vendor-a/model-3": DenyReason.MODEL_BLOCKED,
        "vendor-b/model-1": DenyReason.VENDOR_BLOCKED,
        "vb-large": DenyReason.VENDOR_BLOCKED,
        "vendor-b/model-2": DenyReason.VENDOR_BLOCKED,
        "vendor-a/model-9": DenyReason.UNKNOWN_MODEL,
    }
    assert {name: decide_block(snap, name).reason for name in expected} == expected


@pytest.mark.req("FR-18 (emergency block)", "UX-3")
def test_add_block_records_who_when_and_why_and_bumps_the_version(engine):
    clock = demo_clock()
    with engine.begin() as conn:
        tenant = _tenant(conn)
        before = load_snapshot(conn, tenant)
        add_block(
            conn,
            tenant,
            "vendor",
            "vendor-a",
            "tester",
            "  Incident 42 under investigation ",
            clock,
        )
        after = load_snapshot(conn, tenant)
        assert after.version == before.version + 1
        assert decide_block(after, "model-1").reason is DenyReason.VENDOR_BLOCKED
        change = conn.execute(
            select(registry_changes).order_by(registry_changes.c.id.desc()).limit(1)
        ).one()
        assert (change.subject_id, change.before_status, change.after_status) == (
            "vendor-a",
            "ALLOWED",
            "BLOCKED",
        )
        assert (change.actor, change.reason) == ("tester", "Incident 42 under investigation")
        assert change.changed_at == clock.now()
        conn.rollback()


@pytest.mark.req("FR-18", "SEC-07 (no override by default)")
@pytest.mark.parametrize(
    ("subject_type", "subject_id", "reason", "message"),
    [
        ("vendor", "vendor-b", "A perfectly good reason", "already blocked"),
        ("model", "vendor-a/model-3", "A perfectly good reason", "already blocked"),
        ("vendor", "vendor-z", "A perfectly good reason", "does not exist"),
        ("model", "vendor-a/model-1", "short", "reason"),
        ("budget", "vendor-a", "A perfectly good reason", "Unknown registry item"),
    ],
)
def test_refused_block_changes_nothing(engine, subject_type, subject_id, reason, message):
    with engine.begin() as conn:
        tenant = _tenant(conn)
        before = load_snapshot(conn, tenant)
        changes = conn.execute(select(func.count()).select_from(registry_changes)).scalar_one()
        with pytest.raises(RegistryError, match=message):
            add_block(conn, tenant, subject_type, subject_id, "tester", reason, demo_clock())
        assert load_snapshot(conn, tenant) == before
        assert (
            conn.execute(select(func.count()).select_from(registry_changes)).scalar_one() == changes
        )


@pytest.mark.req("FR-18 (lifting a block requires two administrators)", "SD-03")
def test_there_is_no_code_path_that_lifts_a_block_yet():
    """Until the two-person flow exists (phase 5), nothing may set a status back to ALLOWED."""
    import keepair.registry as registry
    from keepair.config import REPO_ROOT

    assert not [
        n
        for n in dir(registry)
        if "lift" in n.lower() or "unblock" in n.lower() or "allow" in n.lower()
    ]

    # From phase 2 the ledger updates budgets and reservations. The rule is about the
    # registry: only registry.py may update the vendor or model tables.
    def touches_registry_tables(source: str) -> bool:
        imports = re.findall(r"from keepair\.schema import \(?([^)]*?)(?:\)|\n\n)", source, re.S)
        names = {n.strip() for block in imports for n in block.replace("\n", ",").split(",")}
        return bool(names & {"vendors", "models"}) and bool(
            re.search(r"(?<![\w.])update\(", source)
        )

    writers = [
        p.name
        for p in (REPO_ROOT / "src" / "keepair").rglob("*.py")
        if p.name != "registry.py" and touches_registry_tables(p.read_text())
    ]
    assert writers == []
