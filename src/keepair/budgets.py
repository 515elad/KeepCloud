"""Budget arithmetic (FR-04). Pure functions; integers in micro-units only.

Definitions used everywhere (UI now, gateway from phase 2):

    remaining(x)            = cap(x) - committed(x) - reserved(x)
    path(b)                 = b, then each parent reached while the budget below
                              it is a SUBDIVISION. An INDEPENDENT budget ends the
                              path: its parent does not limit it.
    effective_remaining(b)  = min over x in path(b), x enforcing, of remaining(x)

A budget is "enforcing" when its policy is HARD or APPROVAL. MONITOR and SOFT
budgets are evaluated but never limit. If no budget on the path is enforcing,
there is no enforced limit and effective_remaining is None.

Spend recorded on a budget is also recorded on every other budget of its path.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum

from sqlalchemy import Connection, select

from keepair.schema import budgets as budgets_table

ENFORCING = frozenset({"HARD", "APPROVAL"})
TICKS_PCT = (50, 80, 90, 100)


class Mode(StrEnum):
    INDEPENDENT = "INDEPENDENT"
    SUBDIVISION = "SUBDIVISION"


@dataclass(frozen=True, slots=True)
class Budget:
    id: uuid.UUID
    parent_id: uuid.UUID | None
    scope_type: str
    scope_id: uuid.UUID
    cap_micros: int
    currency: str
    period: str
    period_start: object
    mode: str
    policy: str
    committed_micros: int = 0
    reserved_micros: int = 0

    @property
    def enforcing(self) -> bool:
        return self.policy in ENFORCING


BudgetMap = Mapping[uuid.UUID, Budget]


def remaining(b: Budget) -> int:
    return b.cap_micros - b.committed_micros - b.reserved_micros


def constraint_path(b: Budget, all_budgets: BudgetMap) -> list[Budget]:
    path = [b]
    seen = {b.id}
    current = b
    while current.mode == Mode.SUBDIVISION and current.parent_id is not None:
        parent = all_budgets[current.parent_id]
        if parent.id in seen:
            raise ValueError("budget hierarchy contains a cycle")
        path.append(parent)
        seen.add(parent.id)
        current = parent
    return path


@dataclass(frozen=True, slots=True)
class EffectiveRemaining:
    amount_micros: int | None  # None: no enforcing budget on the path
    binding: Budget | None  # the budget whose remaining is the minimum
    path: tuple[Budget, ...]


def effective_remaining(b: Budget, all_budgets: BudgetMap) -> EffectiveRemaining:
    path = constraint_path(b, all_budgets)
    enforcing = [x for x in path if x.enforcing]
    if not enforcing:
        return EffectiveRemaining(None, None, tuple(path))
    binding = min(enforcing, key=remaining)  # first minimum: nearest to b wins ties
    return EffectiveRemaining(remaining(binding), binding, tuple(path))


@dataclass(frozen=True, slots=True)
class Usage:
    """Bar segments in hundredths of a percent of the cap (basis points), floor-rounded."""

    committed_bp: int
    reserved_bp: int
    over_cap_micros: int

    @property
    def used_bp(self) -> int:
        return self.committed_bp + self.reserved_bp


def usage(b: Budget) -> Usage:
    used = b.committed_micros + b.reserved_micros
    if b.cap_micros == 0:
        return Usage(0, 0, used)
    return Usage(
        committed_bp=b.committed_micros * 10_000 // b.cap_micros,
        reserved_bp=b.reserved_micros * 10_000 // b.cap_micros,
        over_cap_micros=max(0, used - b.cap_micros),
    )


def subdivision_overcommit(b: Budget, all_budgets: BudgetMap) -> int:
    """How far the caps of b's SUBDIVISION children add up beyond b's own cap (0 if they fit)."""
    child_caps = sum(
        c.cap_micros
        for c in all_budgets.values()
        if c.parent_id == b.id and c.mode == Mode.SUBDIVISION
    )
    return max(0, child_caps - b.cap_micros)


def currency_mismatches(all_budgets: BudgetMap) -> list[uuid.UUID]:
    """SUBDIVISION budgets in another currency than their parent. Not allowed: no FX yet."""
    return [
        b.id
        for b in all_budgets.values()
        if b.mode == Mode.SUBDIVISION
        and b.parent_id is not None
        and all_budgets[b.parent_id].currency != b.currency
    ]


# --- Pure reserve and settle, shared with the ledger in phase 2 -------------


class Denied(Exception):
    def __init__(self, code: str, budget_id: uuid.UUID) -> None:
        super().__init__(code)
        self.code = code
        self.budget_id = budget_id


def reserve(
    all_budgets: BudgetMap, budget_id: uuid.UUID, cost_micros: int
) -> dict[uuid.UUID, Budget]:
    """Return the budgets after reserving cost on budget_id's path, or raise Denied."""
    if cost_micros < 0:
        raise ValueError("cost must not be negative")
    path = constraint_path(all_budgets[budget_id], all_budgets)
    for x in path:
        if x.enforcing and cost_micros > remaining(x):
            raise Denied("BUDGET_EXHAUSTED", x.id)
    updated = dict(all_budgets)
    for x in path:
        updated[x.id] = replace(x, reserved_micros=x.reserved_micros + cost_micros)
    return updated


def settle(
    all_budgets: BudgetMap, budget_id: uuid.UUID, reserved_micros: int, actual_micros: int
) -> dict[uuid.UUID, Budget]:
    """Turn a reservation into committed spend on the whole path."""
    if actual_micros < 0 or reserved_micros < 0:
        raise ValueError("amounts must not be negative")
    updated = dict(all_budgets)
    for x in constraint_path(all_budgets[budget_id], all_budgets):
        updated[x.id] = replace(
            x,
            reserved_micros=x.reserved_micros - reserved_micros,
            committed_micros=x.committed_micros + actual_micros,
        )
    return updated


def load_budgets(conn: Connection, tenant_id: uuid.UUID) -> dict[uuid.UUID, Budget]:
    t = budgets_table
    rows = conn.execute(select(t).where(t.c.tenant_id == tenant_id))
    return {
        r.id: Budget(
            id=r.id,
            parent_id=r.parent_id,
            scope_type=r.scope_type,
            scope_id=r.scope_id,
            cap_micros=r.cap_micros,
            currency=r.currency,
            period=r.period,
            period_start=r.period_start,
            mode=r.mode,
            policy=r.policy,
            committed_micros=r.committed_micros,
            reserved_micros=r.reserved_micros,
        )
        for r in rows
    }
