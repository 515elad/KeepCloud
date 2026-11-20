"""View models: read the database, call the pure functions, format for templates."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import Connection, func, select

from keepair import budgets as B
from keepair.coverage import Coverage, coverage_state
from keepair.registry import EffectiveStatus, Status, effective_model_status
from keepair.schema import (
    agents,
    budgets,
    gateway_credentials,
    gateway_decisions,
    model_aliases,
    models,
    org_units,
    projects,
    registry_changes,
    unregistered_models,
    vendors,
)
from keepair.web.formatting import (
    format_money,
    format_pct_bp,
    format_period,
    format_unit_price,
)

SCOPE_LABEL = {"ORG": "Organization", "DEPT": "Department", "TEAM": "Team", "PROJECT": "Project"}
POLICY_LABEL = {
    "MONITOR": "Monitor",
    "SOFT": "Soft limit",
    "HARD": "Hard limit",
    "APPROVAL": "Approval",
}
MODE_LABEL = {"INDEPENDENT": "Independent", "SUBDIVISION": "Subdivision"}


@dataclass(slots=True)
class Bar:
    """Budget bar segments as whole percentages of the cap, clamped so they fit the bar."""

    committed_pct: int
    reserved_pct: int
    over_cap: bool
    reached: list[int]
    summary: str
    short: str


@dataclass(slots=True)
class BudgetRow:
    id: uuid.UUID
    name: str
    depth: int
    scope_type: str
    scope_label: str
    policy: str
    policy_label: str
    enforcing: bool
    mode_label: str
    period_text: str
    period_label: str
    period_start: str
    cap_text: str
    committed_text: str
    reserved_text: str
    remaining_text: str
    over_cap: bool
    used_text: str
    bar: Bar
    effective_text: str
    limited_by: str | None
    overcommit_text: str | None
    coverage: Coverage | None
    path: list[PathRow] = field(default_factory=list)
    children: list[tuple[uuid.UUID, str]] = field(default_factory=list)
    parent: tuple[uuid.UUID, str] | None = None


@dataclass(slots=True)
class PathRow:
    id: uuid.UUID
    name: str
    policy_label: str
    enforcing: bool
    remaining_text: str
    binding: bool


def _remaining_text(b: B.Budget) -> str:
    left = B.remaining(b)
    if left < 0:
        return f"Over cap by {format_money(-left, b.currency)}"
    return format_money(left, b.currency)


def _bar(b: B.Budget) -> Bar:
    u = B.usage(b)
    committed = min(u.committed_bp // 100, 100)
    # Round a reservation up to one whole percent so a small one stays visible.
    reserved = min(-(-u.reserved_bp // 100), 100 - committed)
    left = max(0, 10_000 - u.used_bp)
    tail = (
        f"over cap by {format_money(u.over_cap_micros, b.currency)}"
        if u.over_cap_micros
        else f"remaining {format_pct_bp(left)}"
    )
    return Bar(
        committed_pct=committed,
        reserved_pct=reserved,
        over_cap=u.over_cap_micros > 0,
        reached=[t for t in B.TICKS_PCT if u.used_bp >= t * 100],
        summary=f"Committed {format_pct_bp(u.committed_bp)}, reserved "
        f"{format_pct_bp(u.reserved_bp)}, {tail}",
        short=f"{format_pct_bp(u.committed_bp)} committed, {format_pct_bp(u.reserved_bp)} reserved",
    )


def load_scope_names(conn: Connection, tenant_id: uuid.UUID) -> dict[uuid.UUID, str]:
    names = dict(
        conn.execute(
            select(org_units.c.id, org_units.c.name).where(org_units.c.tenant_id == tenant_id)
        ).all()
    )
    names.update(
        conn.execute(
            select(projects.c.id, projects.c.name).where(projects.c.tenant_id == tenant_id)
        ).all()
    )
    return names


def load_budget_rows(conn: Connection, tenant_id: uuid.UUID) -> list[BudgetRow]:
    all_budgets = B.load_budgets(conn, tenant_id)
    names = load_scope_names(conn, tenant_id)
    project_rows = {
        r.id: r for r in conn.execute(select(projects).where(projects.c.tenant_id == tenant_id))
    }

    def name_of(b: B.Budget) -> str:
        return names.get(b.scope_id, "Unnamed scope")

    children: dict[uuid.UUID | None, list[B.Budget]] = {}
    for b in all_budgets.values():
        children.setdefault(b.parent_id, []).append(b)
    for group in children.values():
        group.sort(key=lambda b: names.get(b.scope_id, ""))

    rows: list[BudgetRow] = []

    def visit(b: B.Budget, depth: int) -> None:
        eff = B.effective_remaining(b, all_budgets)
        if eff.amount_micros is None:
            effective_text, limited_by = "No enforced limit", None
        else:
            effective_text = format_money(max(0, eff.amount_micros), b.currency)
            limited_by = name_of(eff.binding) if eff.binding.id != b.id else None
        over = B.subdivision_overcommit(b, all_budgets)
        coverage = None
        if b.scope_type == "PROJECT" and b.scope_id in project_rows:
            p = project_rows[b.scope_id]
            # Uncontrolled findings (FR-19) arrive with reconciliation in phase 4.
            coverage = coverage_state(p.key_custody, p.egress_verified, uncontrolled_finding=False)
        u = B.usage(b)
        parent = all_budgets.get(b.parent_id) if b.parent_id else None
        rows.append(
            BudgetRow(
                id=b.id,
                name=name_of(b),
                depth=depth,
                scope_type=b.scope_type,
                scope_label=SCOPE_LABEL.get(b.scope_type, b.scope_type.title()),
                policy=b.policy,
                policy_label=POLICY_LABEL[b.policy],
                enforcing=b.enforcing,
                mode_label=MODE_LABEL[b.mode],
                period_text=format_period(b.period, b.period_start),
                period_label=b.period.capitalize(),
                period_start=b.period_start.isoformat(),
                cap_text=format_money(b.cap_micros, b.currency),
                committed_text=format_money(b.committed_micros, b.currency),
                reserved_text=format_money(b.reserved_micros, b.currency),
                remaining_text=_remaining_text(b),
                over_cap=B.remaining(b) < 0,
                used_text=format_pct_bp(u.used_bp),
                bar=_bar(b),
                effective_text=effective_text,
                limited_by=limited_by,
                overcommit_text=format_money(over, b.currency) if over else None,
                coverage=coverage,
                path=[
                    PathRow(
                        id=x.id,
                        name=name_of(x),
                        policy_label=POLICY_LABEL[x.policy],
                        enforcing=x.enforcing,
                        remaining_text=_remaining_text(x),
                        binding=eff.binding is not None and x.id == eff.binding.id,
                    )
                    for x in eff.path
                ],
                children=[(c.id, name_of(c)) for c in children.get(b.id, [])],
                parent=(parent.id, name_of(parent)) if parent else None,
            )
        )
        for child in children.get(b.id, []):
            visit(child, depth + 1)

    for root in children.get(None, []):
        visit(root, 0)
    return rows


# --- Registry --------------------------------------------------------------


@dataclass(slots=True)
class Change:
    actor: str
    reason: str
    changed_at: datetime
    after_status: str


@dataclass(slots=True)
class VendorRow:
    id: str
    status: Status
    model_count: int
    last_change: Change | None


@dataclass(slots=True)
class ModelRow:
    id: str
    vendor_id: str
    own_status: Status
    effective: EffectiveStatus
    aliases: list[str]
    input_price: str
    output_price: str
    max_output_tokens: int
    last_change: Change | None

    @property
    def dom_id(self) -> str:
        return self.id.replace("/", "--")


@dataclass(slots=True)
class UnregisteredRow:
    name: str
    first_seen_at: datetime
    last_seen_at: datetime
    seen_count: int


@dataclass(slots=True)
class RegistryView:
    vendors: list[VendorRow]
    models: list[ModelRow]
    unregistered: list[UnregisteredRow]


def load_registry(conn: Connection, tenant_id: uuid.UUID) -> RegistryView:
    last: dict[tuple[str, str], Change] = {}
    for r in conn.execute(
        select(registry_changes)
        .where(registry_changes.c.tenant_id == tenant_id)
        .order_by(registry_changes.c.changed_at, registry_changes.c.id)
    ):
        last[(r.subject_type, r.subject_id)] = Change(
            r.actor, r.reason, r.changed_at, r.after_status
        )
    vendor_rows = conn.execute(
        select(vendors).where(vendors.c.tenant_id == tenant_id).order_by(vendors.c.id)
    ).all()
    model_rows = conn.execute(
        select(models).where(models.c.tenant_id == tenant_id).order_by(models.c.id)
    ).all()
    aliases: dict[str, list[str]] = {}
    for r in conn.execute(
        select(model_aliases)
        .where(model_aliases.c.tenant_id == tenant_id)
        .order_by(model_aliases.c.alias)
    ):
        aliases.setdefault(r.model_id, []).append(r.alias)
    vendor_status = {v.id: Status(v.status) for v in vendor_rows}
    return RegistryView(
        vendors=[
            VendorRow(
                v.id,
                Status(v.status),
                sum(1 for m in model_rows if m.vendor_id == v.id),
                last.get(("vendor", v.id)),
            )
            for v in vendor_rows
        ],
        models=[
            ModelRow(
                id=m.id,
                vendor_id=m.vendor_id,
                own_status=Status(m.status),
                effective=effective_model_status(vendor_status[m.vendor_id], Status(m.status)),
                aliases=aliases.get(m.id, []),
                input_price=format_unit_price(m.input_price_micros_per_1k, m.price_currency),
                output_price=format_unit_price(m.output_price_micros_per_1k, m.price_currency),
                max_output_tokens=m.max_output_tokens,
                last_change=last.get(("model", m.id)),
            )
            for m in model_rows
        ],
        unregistered=[
            UnregisteredRow(r.requested_name, r.first_seen_at, r.last_seen_at, r.seen_count)
            for r in conn.execute(
                select(unregistered_models)
                .where(unregistered_models.c.tenant_id == tenant_id)
                .order_by(unregistered_models.c.requested_name)
            )
        ],
    )


# --- Gateway activity: denials feed (UX-5) and credentials -------------------

REASON_TEXT = {
    "VENDOR_BLOCKED": "The vendor is blocked",
    "MODEL_BLOCKED": "The model is blocked",
    "MODEL_NOT_ALLOWED": "The model is not allowed",
    "UNKNOWN_MODEL": "The model is not registered",
    "VENDOR_ROUTE_MISMATCH": "The model does not belong to the vendor in the address",
    "SNAPSHOT_STALE": "Policy could not be refreshed, so every request is refused",
    "BUDGET_EXHAUSTED": "The budget has no room for this request",
    "NO_BUDGET": "The project has no budget",
    "FX_RATE_MISSING": "No exchange rate for the budget's currency",
    "APPROVAL_REQUIRED": "Held until an approver decides",
    "RATE_LIMITED": "Too many open requests for this credential",
    "LEDGER_UNAVAILABLE": "The ledger could not be reached",
    "UPSTREAM_TIMEOUT": "The vendor did not answer in time",
    "UPSTREAM_ERROR": "The vendor returned an error",
}
WINDOW_HOURS = 24
FEED_LIMIT = 50


@dataclass(slots=True)
class DenialRow:
    occurred_at: datetime
    agent: str
    project: str
    requested_model: str
    outcome: str
    code: str
    reason: str
    budget: str | None
    request_id: uuid.UUID


@dataclass(slots=True)
class ReasonSummary:
    code: str
    reason: str
    count: int
    points: str  # SVG polyline points, one per hour, oldest first
    peak: int


@dataclass(slots=True)
class Activity:
    requests: int
    refused: int
    held: int
    last_request_at: datetime | None
    reasons: list[ReasonSummary]
    feed: list[DenialRow]


def count_by_reason(rows) -> dict[str, int]:
    """refusals(reason) = number of denied or held requests with that reason in the window."""
    counts: dict[str, int] = {}
    for r in rows:
        if r.outcome != "ALLOWED" and r.reason_code:
            counts[r.reason_code] = counts.get(r.reason_code, 0) + 1
    return counts


def _sparkline(buckets: list[int]) -> str:
    peak = max(buckets) or 1
    return " ".join(f"{i * 4 + 2},{18 - round(16 * n / peak)}" for i, n in enumerate(buckets))


def load_activity(conn: Connection, tenant_id: uuid.UUID, now: datetime) -> Activity:
    d = gateway_decisions
    since = now - timedelta(hours=WINDOW_HOURS)
    rows = conn.execute(
        select(d)
        .where(d.c.tenant_id == tenant_id, d.c.occurred_at > since)
        .order_by(d.c.occurred_at.desc(), d.c.id.desc())
    ).all()
    last = conn.execute(
        select(d.c.occurred_at)
        .where(d.c.tenant_id == tenant_id)
        .order_by(d.c.occurred_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    names = load_scope_names(conn, tenant_id)
    budget_scope = dict(
        conn.execute(
            select(budgets.c.id, budgets.c.scope_id).where(budgets.c.tenant_id == tenant_id)
        ).all()
    )
    counts = count_by_reason(rows)
    reasons = []
    for code, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        buckets = [0] * WINDOW_HOURS
        for r in rows:
            if r.outcome != "ALLOWED" and r.reason_code == code:
                age_h = int((now - r.occurred_at).total_seconds() // 3600)
                buckets[WINDOW_HOURS - 1 - min(max(age_h, 0), WINDOW_HOURS - 1)] += 1
        reasons.append(
            ReasonSummary(
                code, REASON_TEXT.get(code, "Refused"), count, _sparkline(buckets), max(buckets)
            )
        )
    feed = [
        DenialRow(
            occurred_at=r.occurred_at,
            agent=r.agent or "Unknown",
            project=r.project or "Unknown",
            requested_model=r.requested_model or "",
            outcome=r.outcome,
            code=r.reason_code or "",
            reason=REASON_TEXT.get(r.reason_code, "Refused"),
            budget=names.get(budget_scope.get(r.budget_id)) if r.budget_id else None,
            request_id=r.id,
        )
        for r in rows
        if r.outcome != "ALLOWED"
    ][:FEED_LIMIT]
    return Activity(
        requests=len(rows),
        refused=sum(1 for r in rows if r.outcome == "DENIED"),
        held=sum(1 for r in rows if r.outcome == "HELD"),
        last_request_at=last,
        reasons=reasons,
        feed=feed,
    )


@dataclass(slots=True)
class CredentialRow:
    id: uuid.UUID
    agent: str
    project: str
    label: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    status: str


def credential_status(revoked_at: datetime | None, expires_at: datetime, now: datetime) -> str:
    """status = Revoked when revoked, Expired when past its expiry, otherwise Active."""
    if revoked_at is not None:
        return "Revoked"
    return "Expired" if expires_at <= now else "Active"


@dataclass(slots=True)
class CredentialsView:
    rows: list[CredentialRow]
    agents: list[tuple[uuid.UUID, str, str]]  # id, agent, project


def load_credentials(conn: Connection, tenant_id: uuid.UUID) -> CredentialsView:
    a, c = agents, gateway_credentials
    db_now = conn.execute(select(func.now())).scalar_one()  # expiry is judged by the database clock
    rows = conn.execute(
        select(c, a.c.name.label("agent"), projects.c.name.label("project"))
        .select_from(
            c.join(a, a.c.id == c.c.agent_id).join(projects, projects.c.id == a.c.project_id)
        )
        .where(c.c.tenant_id == tenant_id)
        .order_by(a.c.name, c.c.created_at)
    ).all()
    agent_rows = conn.execute(
        select(a.c.id, a.c.name, projects.c.name)
        .select_from(a.join(projects, projects.c.id == a.c.project_id))
        .where(a.c.tenant_id == tenant_id)
        .order_by(a.c.name)
    ).all()
    return CredentialsView(
        rows=[
            CredentialRow(
                r.id,
                r.agent,
                r.project,
                r.label,
                r.created_at,
                r.expires_at,
                r.revoked_at,
                credential_status(r.revoked_at, r.expires_at, db_now),
            )
            for r in rows
        ],
        agents=[tuple(r) for r in agent_rows],
    )
