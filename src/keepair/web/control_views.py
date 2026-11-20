"""View models for people, approvals, the kill switch and owners (phase 5)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import Connection, func, select

from keepair import approvals as A
from keepair import budgets as B
from keepair import killswitch
from keepair.billing.finalization import Figure, Finalization
from keepair.clock import Clock
from keepair.permissions import ROLE_LABEL, Role
from keepair.schema import (
    agents,
    approvals,
    budgets,
    kill_switches,
    projects,
    reservations,
    usage_events,
    users,
    vendors,
)
from keepair.web.formatting import format_money, format_unit_price
from keepair.web.views import POLICY_LABEL, load_scope_names

WHY_NOT = {
    "SELF_APPROVAL": "This request comes from your own project. Someone else must decide it.",
    "NOT_ELIGIBLE": "Only an administrator or the owner of a budget above this project can decide.",
}


def _amount(micros: int, currency: str) -> str:
    # One request often costs less than a cent: keep the decimals that show it.
    if 0 < micros < 10_000:
        return format_unit_price(micros, currency)
    return format_money(micros, currency)


@dataclass(slots=True)
class HeldRow:
    reservation_id: uuid.UUID
    created_at: datetime
    agent: str
    project: str
    model: str
    amount_text: str
    budget_id: uuid.UUID
    budget_name: str
    left_text: str
    expires_at: datetime
    approved: bool
    why_not: str | None


def held_rows(conn: Connection, tenant_id: uuid.UUID, actor) -> list[HeldRow]:
    """Requests waiting for a decision, and approved ones waiting to be sent again."""
    r, a, p = reservations, agents, projects
    rows = conn.execute(
        select(r, a.c.name.label("agent"), p.c.name.label("project"))
        .select_from(r.outerjoin(a, a.c.id == r.c.agent_id).outerjoin(p, p.c.id == a.c.project_id))
        .where(
            r.c.tenant_id == tenant_id,
            r.c.state.in_(("HELD", "APPROVED")),
            r.c.expires_at > func.now(),
        )
        .order_by(r.c.created_at.desc(), r.c.id.desc())  # newest first
    ).all()
    if not rows:
        return []
    all_budgets = B.load_budgets(conn, tenant_id)
    names = load_scope_names(conn, tenant_id)
    owner_of = dict(
        conn.execute(
            select(budgets.c.id, budgets.c.owner_user_id).where(budgets.c.tenant_id == tenant_id)
        ).all()
    )
    out = []
    for row in rows:
        budget = all_budgets[row.budget_id]
        left = B.effective_remaining(budget, all_budgets).amount_micros
        above = [owner_of.get(b) for b in row.budget_path if b != row.budget_id]
        problem = A.held_eligibility(actor.id, actor.role, owner_of.get(row.budget_id), above)
        out.append(
            HeldRow(
                reservation_id=row.id,
                created_at=row.created_at,
                agent=row.agent or "Unknown",
                project=row.project or "Unknown",
                model=row.model_id or "",
                amount_text=_amount(row.reserved_micros, row.currency),
                budget_id=row.budget_id,
                budget_name=names.get(budget.scope_id, "Unknown"),
                left_text="No enforced limit" if left is None
                else format_money(max(0, left), budget.currency),
                expires_at=row.expires_at,
                approved=row.state == "APPROVED",
                why_not=WHY_NOT.get(problem) if problem else None,
            )
        )  # fmt: skip
    return out


@dataclass(slots=True)
class PendingRow:
    id: uuid.UUID
    kind: str
    kind_label: str
    summary: str
    requested_by: str
    requested_at: datetime
    reason: str
    expires_at: datetime
    eligible: list[str]
    mine: bool
    can_decide: bool


def pending_rows(conn: Connection, clock: Clock, tenant_id: uuid.UUID, actor) -> list[PendingRow]:
    a = approvals
    rows = conn.execute(
        select(a)
        .where(
            a.c.tenant_id == tenant_id,
            a.c.decision.is_(None),
            a.c.kind.in_(A.TWO_PERSON_KINDS),
            a.c.expires_at > clock.now(),
        )
        .order_by(a.c.requested_at, a.c.id)
    ).all()
    return [
        PendingRow(
            id=r.id,
            kind=r.kind,
            kind_label=A.KIND_LABEL[r.kind],
            summary=r.summary,
            requested_by=r.requested_by_name,
            requested_at=r.requested_at,
            reason=r.reason,
            expires_at=r.expires_at,
            eligible=A.eligible_approvers(conn, tenant_id, r.requested_by),
            mine=r.requested_by == actor.id,
            can_decide=A.may_decide(r.requested_by, actor.id, actor.role),
        )
        for r in rows
    ]


def pending_lifts(conn: Connection, tenant_id: uuid.UUID) -> dict[tuple[str, str], str]:
    """Registry items with a lift request waiting: (type, id) -> requester."""
    a = approvals
    rows = conn.execute(
        select(a.c.subject_type, a.c.subject_id, a.c.requested_by_name).where(
            a.c.tenant_id == tenant_id, a.c.kind == "BLOCK_LIFT", a.c.decision.is_(None)
        )
    )
    return {(r.subject_type, r.subject_id): r.requested_by_name for r in rows}


@dataclass(slots=True)
class DecisionRow:
    decided_at: datetime
    kind_label: str
    summary: str
    requested_by: str
    decision: str
    decided_by: str


DECISION_LABEL = {
    "APPROVED": "Approved",
    "REJECTED": "Rejected",
    "EXPIRED": "Expired, nothing changed",
    "CANCELLED": "Cancelled by the requester",
}


def recent_decisions(conn: Connection, tenant_id: uuid.UUID, limit: int = 20) -> list[DecisionRow]:
    a = approvals
    rows = conn.execute(
        select(a)
        .where(a.c.tenant_id == tenant_id, a.c.decision.is_not(None))
        .order_by(a.c.decided_at.desc(), a.c.id.desc())
        .limit(limit)
    ).all()
    return [
        DecisionRow(
            r.decided_at, A.KIND_LABEL[r.kind], r.summary, r.requested_by_name,
            DECISION_LABEL[r.decision], r.decided_by_name or "system",
        )
        for r in rows
    ]  # fmt: skip


@dataclass(slots=True)
class UserRow:
    id: uuid.UUID
    username: str
    display_name: str
    role_label: str
    active: bool
    locked: bool
    created_at: datetime
    owns: int
    is_self: bool


def user_rows(conn: Connection, clock: Clock, tenant_id: uuid.UUID, actor) -> list[UserRow]:
    owned = dict(
        conn.execute(
            select(budgets.c.owner_user_id, func.count())
            .where(budgets.c.tenant_id == tenant_id, budgets.c.owner_user_id.is_not(None))
            .group_by(budgets.c.owner_user_id)
        ).all()
    )
    rows = conn.execute(
        select(users).where(users.c.tenant_id == tenant_id).order_by(users.c.username)
    ).all()
    now = clock.now()
    return [
        UserRow(
            id=u.id,
            username=u.username,
            display_name=u.display_name,
            role_label=ROLE_LABEL[Role(u.role)],
            active=u.status == "ACTIVE",
            locked=u.locked_until is not None and u.locked_until > now,
            created_at=u.created_at,
            owns=owned.get(u.id, 0),
            is_self=u.id == actor.id,
        )
        for u in rows
    ]


def owner_choices(conn: Connection, tenant_id: uuid.UUID) -> list[tuple[uuid.UUID, str]]:
    rows = conn.execute(
        select(users.c.id, users.c.display_name, users.c.username)
        .where(users.c.tenant_id == tenant_id, users.c.status == "ACTIVE")
        .order_by(users.c.display_name)
    )
    return [(r.id, f"{r.display_name} ({r.username})") for r in rows]


@dataclass(slots=True)
class SwitchRow:
    id: uuid.UUID
    scope_label: str
    scope_name: str
    reason: str
    activated_by: str
    activated_at: datetime
    deactivated_at: datetime | None
    deactivated_by: str | None
    off_requested_by: str | None


def _switch_rows(conn: Connection, tenant_id: uuid.UUID, active: bool) -> list[SwitchRow]:
    k, a = kill_switches, approvals
    waiting = dict(
        conn.execute(
            select(a.c.subject_id, a.c.requested_by_name).where(
                a.c.tenant_id == tenant_id, a.c.kind == "KILL_SWITCH_OFF", a.c.decision.is_(None)
            )
        ).all()
    )
    condition = k.c.deactivated_at.is_(None) if active else k.c.deactivated_at.is_not(None)
    rows = conn.execute(
        select(k)
        .where(k.c.tenant_id == tenant_id, condition)
        .order_by(k.c.activated_at.desc(), k.c.id.desc())
        .limit(20)
    ).all()
    return [
        SwitchRow(
            r.id, killswitch.SCOPE_LABEL[r.scope_type], r.scope_name, r.reason,
            r.activated_by_name, r.activated_at, r.deactivated_at, r.deactivated_by_name,
            waiting.get(str(r.id)),
        )
        for r in rows
    ]  # fmt: skip


def active_switches(conn: Connection, tenant_id: uuid.UUID) -> list[SwitchRow]:
    return _switch_rows(conn, tenant_id, True)


def past_switches(conn: Connection, tenant_id: uuid.UUID) -> list[SwitchRow]:
    return _switch_rows(conn, tenant_id, False)


def scope_choices(conn: Connection, tenant_id: uuid.UUID) -> dict:
    return {
        "vendors": list(
            conn.execute(
                select(vendors.c.id).where(vendors.c.tenant_id == tenant_id).order_by(vendors.c.id)
            ).scalars()
        ),
        "projects": [
            (str(r.id), r.name)
            for r in conn.execute(
                select(projects.c.id, projects.c.name)
                .where(projects.c.tenant_id == tenant_id)
                .order_by(projects.c.name)
            )
        ],
    }


# --- Unowned spend (FR-17) ----------------------------------------------------------


@dataclass(slots=True)
class Unowned:
    budgets: list[tuple[uuid.UUID, str]]
    figure: Figure | None
    text: str


def unowned_spend(usage: list[tuple[str | None, str | None, int]], owned: set[str]) -> int:
    """unowned = sum of estimated cost of usage whose scope has no active owner.

    ``usage`` rows are (project, team, cost). The scope of a row is its project, or
    its team when it names no project. A row that names neither is unowned.
    """
    return sum(cost for project, team, cost in usage if (project or team) not in owned)


def owned_scope_names(conn: Connection, tenant_id: uuid.UUID) -> tuple[set[str], list]:
    """Names of scopes whose budget has an active owner, and the budgets that have none."""
    names = load_scope_names(conn, tenant_id)
    rows = conn.execute(
        select(budgets.c.id, budgets.c.scope_id, users.c.status)
        .select_from(budgets.outerjoin(users, users.c.id == budgets.c.owner_user_id))
        .where(budgets.c.tenant_id == tenant_id)
    ).all()
    owned = {names.get(r.scope_id, "") for r in rows if r.status == "ACTIVE"}
    missing = sorted(
        ((r.id, names.get(r.scope_id, "Unnamed scope")) for r in rows if r.status != "ACTIVE"),
        key=lambda item: item[1],
    )
    return owned, missing


def period_usage(conn: Connection, tenant_id: uuid.UUID, period: date) -> tuple[list, str | None]:
    u = usage_events
    end = date(period.year + period.month // 12, period.month % 12 + 1, 1)
    rows = conn.execute(
        select(u.c.project, u.c.team, u.c.price_micros, u.c.price_currency).where(
            u.c.tenant_id == tenant_id,
            u.c.price_micros.is_not(None),
            func.date(func.timezone("UTC", u.c.occurred_at)) >= period,
            func.date(func.timezone("UTC", u.c.occurred_at)) < end,
        )
    ).all()
    currency = rows[0].price_currency if rows else None
    return [(r.project, r.team, r.price_micros) for r in rows], currency


def unowned(conn: Connection, tenant_id: uuid.UUID, period: date | None) -> Unowned:
    owned, missing = owned_scope_names(conn, tenant_id)
    if period is None:
        return Unowned(missing, None, "No data")
    usage, currency = period_usage(conn, tenant_id, period)
    if currency is None:
        return Unowned(missing, None, "No data")
    total = unowned_spend(usage, owned)
    return Unowned(
        missing, Figure(total, currency, Finalization.ESTIMATED), format_money(total, currency)
    )


def policy_choices(current: str) -> list[tuple[str, str]]:
    return [(code, label) for code, label in POLICY_LABEL.items() if code != current]
