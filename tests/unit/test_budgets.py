"""FR-04: effective remaining allowance. Pure, no database."""

import uuid
from datetime import date

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from keepair import budgets as B

pytestmark = pytest.mark.req("FR-04")

U = 1_000_000


def make(
    n,
    parent=None,
    cap=100,
    committed=0,
    reserved=0,
    policy="HARD",
    mode="SUBDIVISION",
    currency="USD",
):
    return B.Budget(
        id=uuid.UUID(int=n),
        parent_id=uuid.UUID(int=parent) if parent is not None else None,
        scope_type="TEAM",
        scope_id=uuid.UUID(int=1000 + n),
        cap_micros=cap * U,
        currency=currency,
        period="MONTH",
        period_start=date(2026, 1, 1),
        mode="INDEPENDENT" if parent is None else mode,
        policy=policy,
        committed_micros=committed * U,
        reserved_micros=reserved * U,
    )


def tree(*budgets):
    return {b.id: b for b in budgets}


def test_remaining_is_cap_minus_committed_minus_reserved():
    assert B.remaining(make(1, cap=100, committed=30, reserved=5)) == 65 * U


def test_hierarchy_ancestor_cap_enforced_when_child_has_room():
    parent = make(1, cap=100, committed=95)
    child = make(2, parent=1, cap=50, committed=10)
    all_budgets = tree(parent, child)
    eff = B.effective_remaining(child, all_budgets)
    assert eff.amount_micros == 5 * U and eff.binding.id == parent.id
    with pytest.raises(B.Denied) as denied:
        B.reserve(all_budgets, child.id, 6 * U)
    assert denied.value.code == "BUDGET_EXHAUSTED" and denied.value.budget_id == parent.id
    assert B.reserve(all_budgets, child.id, 5 * U)[parent.id].reserved_micros == 5 * U


def test_independent_child_ignores_parent_remaining_for_own_cap():
    parent = make(1, cap=100, committed=100)
    child = make(2, parent=1, cap=50, committed=10, mode="INDEPENDENT")
    all_budgets = tree(parent, child)
    eff = B.effective_remaining(child, all_budgets)
    assert eff.amount_micros == 40 * U and [x.id for x in eff.path] == [child.id]
    after = B.reserve(all_budgets, child.id, 40 * U)
    assert after[parent.id] == parent  # independent spend is not recorded on the parent


def test_monitor_and_soft_budgets_never_limit():
    parent = make(1, cap=10, committed=50, policy="SOFT")
    child = make(2, parent=1, cap=10, committed=50, policy="MONITOR")
    all_budgets = tree(parent, child)
    assert B.effective_remaining(child, all_budgets).amount_micros is None
    after = B.reserve(all_budgets, child.id, 1_000 * U)  # evaluated, never blocked
    assert (
        after[child.id].reserved_micros == 1_000 * U
        and after[parent.id].reserved_micros == 1_000 * U
    )


def test_soft_budget_between_hard_ones_is_skipped_not_a_barrier():
    top = make(1, cap=100, committed=90)
    middle = make(2, parent=1, cap=10, committed=10, policy="SOFT")
    leaf = make(3, parent=2, cap=50)
    eff = B.effective_remaining(leaf, tree(top, middle, leaf))
    assert eff.amount_micros == 10 * U and eff.binding.id == top.id


def test_tie_goes_to_the_budget_nearest_the_request():
    parent, child = make(1, cap=20), make(2, parent=1, cap=20)
    assert B.effective_remaining(child, tree(parent, child)).binding.id == child.id


def test_cycle_is_detected():
    a, b = make(1, parent=2), make(2, parent=1)
    with pytest.raises(ValueError, match="cycle"):
        B.constraint_path(a, tree(a, b))


@pytest.mark.req("FR-04", "UX-8")
def test_usage_shares_and_over_cap():
    u = B.usage(make(1, cap=35_000, committed=14_000, reserved=1_750))
    assert (u.committed_bp, u.reserved_bp, u.over_cap_micros) == (4_000, 500, 0)
    over = B.usage(make(1, cap=6_000, committed=7_080))
    assert over.committed_bp == 11_800 and over.over_cap_micros == 1_080 * U
    assert B.usage(make(1, cap=0, committed=3)) == B.Usage(0, 0, 3 * U)
    assert B.TICKS_PCT == (50, 80, 90, 100)


@pytest.mark.req("FR-04", "UX-8 (subdivision warning)")
def test_subdivision_overcommit_counts_only_subdivision_children():
    parent = make(1, cap=100)
    kids = [
        make(2, parent=1, cap=70),
        make(3, parent=1, cap=60),
        make(4, parent=1, cap=500, mode="INDEPENDENT"),
    ]
    assert B.subdivision_overcommit(parent, tree(parent, *kids)) == 30 * U
    assert B.subdivision_overcommit(parent, tree(parent, kids[0])) == 0


def test_subdivision_in_another_currency_is_reported():
    parent, child = make(1), make(2, parent=1, currency="EUR")
    independent = make(3, parent=1, currency="EUR", mode="INDEPENDENT")
    assert B.currency_mismatches(tree(parent, child, independent)) == [child.id]


# --- Property tests ---------------------------------------------------------

node = st.tuples(
    st.integers(min_value=0, max_value=200),  # cap in units
    st.sampled_from(["MONITOR", "SOFT", "HARD", "APPROVAL"]),
    st.sampled_from(["INDEPENDENT", "SUBDIVISION"]),
    st.integers(min_value=0, max_value=10**6),  # picks the parent
)


@st.composite
def trees(draw):
    specs = draw(st.lists(node, min_size=1, max_size=7))
    budgets = []
    for i, (cap, policy, mode, pick) in enumerate(specs):
        parent = pick % i if i else None
        budgets.append(
            make(
                i + 1,
                parent=parent + 1 if parent is not None else None,
                cap=cap,
                policy=policy,
                mode=mode,
            )
        )
    return tree(*budgets)


operations = st.lists(
    st.tuples(
        st.integers(min_value=0, max_value=10**6),
        st.integers(min_value=0, max_value=120),
        st.integers(min_value=0, max_value=100),
    ),
    max_size=30,
)


@given(trees())
def test_effective_remaining_is_the_minimum_over_the_enforcing_path(all_budgets):
    for b in all_budgets.values():
        eff = B.effective_remaining(b, all_budgets)
        enforcing = [x for x in B.constraint_path(b, all_budgets) if x.enforcing]
        if not enforcing:
            assert eff.amount_micros is None and eff.binding is None
            continue
        assert eff.amount_micros == min(B.remaining(x) for x in enforcing)
        assert all(eff.amount_micros <= B.remaining(x) for x in enforcing)
        assert eff.path[0].id == b.id


@settings(max_examples=200)
@given(trees(), operations)
def test_effective_remaining_never_negative_after_any_reserve_and_settle_sequence(all_budgets, ops):
    """Reserve what is allowed, settle at or below it: no enforcing budget goes below zero."""
    ids = sorted(all_budgets)
    open_reservations = []
    for pick, cost_units, settle_pct in ops:
        target = ids[pick % len(ids)]
        cost = cost_units * U
        try:
            all_budgets = B.reserve(all_budgets, target, cost)
            open_reservations.append((target, cost))
        except B.Denied as denied:
            blocker = all_budgets[denied.budget_id]
            assert blocker.enforcing and cost > B.remaining(blocker)
        if open_reservations and settle_pct % 3 == 0:
            settled_target, reserved = open_reservations.pop(0)
            actual = reserved * settle_pct // 100
            all_budgets = B.settle(all_budgets, settled_target, reserved, actual)
        for b in all_budgets.values():
            assert b.reserved_micros >= 0 and b.committed_micros >= 0
            if b.enforcing:
                assert B.remaining(b) >= 0
            eff = B.effective_remaining(b, all_budgets).amount_micros
            assert eff is None or eff >= 0


def test_reserve_and_settle_reject_negative_amounts():
    all_budgets = tree(make(1))
    with pytest.raises(ValueError):
        B.reserve(all_budgets, uuid.UUID(int=1), -1)
    with pytest.raises(ValueError):
        B.settle(all_budgets, uuid.UUID(int=1), 1, -1)
