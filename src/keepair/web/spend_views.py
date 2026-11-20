"""View models for the Spend and Reconciliation pages (FR-03, FR-06, FR-07, FR-19).

Amounts of different finalization states are loaded and shown separately.
Nothing here adds an estimate to a billed amount.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import Connection, func, select

from keepair.billing import reconcile
from keepair.billing.finalization import (
    LABEL,
    SOURCES,
    Figure,
    Finalization,
    billing_figure,
    gateway_figure,
)
from keepair.schema import (
    allocation_facts,
    ingestion_batches,
    normalized_cost_records,
    org_units,
    projects,
    usage_events,
)
from keepair.web.formatting import format_money, format_pct_bp

BILLING_CURRENCY = "USD"
STATES = (Finalization.ESTIMATED, Finalization.PROVIDER_REPORTED, Finalization.INVOICED)
QUEUE_STATES = ("REVIEW", "UNMATCHED", "UNALLOCATED")
QUEUE_LABEL = {
    "REVIEW": "To review",
    "UNMATCHED": "Unmatched",
    "UNALLOCATED": "Unallocated",
    "ALLOCATED": "Allocated",
}
CHART_W, CHART_H, CHART_PAD = 300, 84, 4


def month_of(day: date) -> date:
    return date(day.year, day.month, 1)


def periods(conn: Connection, tenant_id: uuid.UUID) -> tuple[list[date], date | None]:
    """Months that have data, newest first, and the one to show by default."""
    n, u = normalized_cost_records, usage_events
    billed = set(
        conn.execute(
            select(n.c.billing_period).where(n.c.tenant_id == tenant_id).distinct()
        ).scalars()
    )
    used = {
        month_of(d)
        for d in conn.execute(
            select(func.date_trunc("month", u.c.occurred_at))
            .where(u.c.tenant_id == tenant_id, u.c.price_micros.is_not(None))
            .distinct()
        ).scalars()
    }
    found = sorted(billed | used, reverse=True)
    # Prefer the newest month that has billing data: that is where there is something to compare.
    default = max(billed) if billed else (min(used) if used else None)
    return found, default


def parse_period(text: str | None, found: list[date], default: date | None) -> date | None:
    try:
        wanted = date.fromisoformat(f"{text}-01") if text else None
    except ValueError:
        wanted = None
    return wanted if wanted in found else default


@dataclass(slots=True)
class StateTotal:
    figure: Figure
    text: str
    label: str
    has_data: bool


def state_totals(conn: Connection, tenant_id: uuid.UUID, period: date) -> list[StateTotal]:
    start, end = reconcile.period_bounds(period)
    u, n = usage_events, normalized_cost_records
    estimated, events = conn.execute(
        select(func.coalesce(func.sum(u.c.price_micros), 0), func.count()).where(
            u.c.tenant_id == tenant_id, u.c.price_currency == BILLING_CURRENCY,
            u.c.occurred_at >= start, u.c.occurred_at < end,
        )
    ).one()  # fmt: skip
    billed = {
        r.finalization_state: (int(r.total), r.rows)
        for r in conn.execute(
            select(n.c.finalization_state, func.sum(n.c.billed_micros).label("total"),
                   func.count().label("rows"))
            .where(n.c.tenant_id == tenant_id, n.c.is_current, n.c.billing_period == period,
                   n.c.currency == BILLING_CURRENCY)
            .group_by(n.c.finalization_state)
        )
    }  # fmt: skip
    figures = [(gateway_figure(int(estimated), BILLING_CURRENCY), events)]
    for state in (Finalization.PROVIDER_REPORTED, Finalization.INVOICED):
        amount, rows = billed.get(state.value, (0, 0))
        figures.append((billing_figure(amount, BILLING_CURRENCY, state.value), rows))
    return [
        StateTotal(f, format_money(f.amount_micros, f.currency), LABEL[f.state], rows > 0)
        for f, rows in figures
    ]


# --- cost explorer: small multiples by model -----------------------------------


@dataclass(slots=True)
class Bar:
    x: str
    y: str
    width: str
    height: str
    state: str


@dataclass(slots=True)
class ModelChart:
    model: str
    days: list[tuple[date, dict[str, int]]]
    totals: dict[str, int]
    bars: list[Bar] = field(default_factory=list)
    summary: str = ""

    def text(self, state: str) -> str:
        return format_money(self.totals.get(state, 0), BILLING_CURRENCY)


def explorer(conn: Connection, tenant_id: uuid.UUID, period: date) -> tuple[list[ModelChart], str]:
    """One small chart per model, all on the same scale. Returns the charts and the scale's top."""
    start, end = reconcile.period_bounds(period)
    u, n = usage_events, normalized_cost_records
    data: dict[str, dict[date, dict[str, int]]] = {}

    def add(model: str, day: date, state: str, amount: int) -> None:
        cell = data.setdefault(model, {}).setdefault(day, {})
        cell[state] = cell.get(state, 0) + int(amount)

    day_of = func.date(func.timezone("UTC", u.c.occurred_at))
    for r in conn.execute(
        select(u.c.model_id, day_of.label("day"), func.sum(u.c.price_micros).label("total"))
        .where(u.c.tenant_id == tenant_id, u.c.price_currency == BILLING_CURRENCY,
               u.c.occurred_at >= start, u.c.occurred_at < end)
        .group_by(u.c.model_id, day_of)
    ):  # fmt: skip
        add(r.model_id, r.day, "ESTIMATED", r.total)
    for r in conn.execute(
        select(n.c.model_id, n.c.charge_date, n.c.finalization_state,
               func.sum(n.c.billed_micros).label("total"))
        .where(n.c.tenant_id == tenant_id, n.c.is_current, n.c.billing_period == period,
               n.c.currency == BILLING_CURRENCY)
        .group_by(n.c.model_id, n.c.charge_date, n.c.finalization_state)
    ):  # fmt: skip
        add(r.model_id, r.charge_date, r.finalization_state, r.total)

    all_days = sorted({d for by_day in data.values() for d in by_day})
    if not all_days:
        return [], ""
    span = [all_days[0] + timedelta(days=i) for i in range((all_days[-1] - all_days[0]).days + 1)]
    top = (
        max(
            (v for by_day in data.values() for cell in by_day.values() for v in cell.values()),
            default=0,
        )
        or 1
    )
    charts = []
    slot = (CHART_W - 2 * CHART_PAD) / len(span)
    bar_w = slot / 3.6
    for model, by_day in data.items():
        chart = ModelChart(
            model=model,
            days=[(d, by_day.get(d, {})) for d in span],
            totals={s.value: sum(c.get(s.value, 0) for c in by_day.values()) for s in STATES},
        )
        for index, day in enumerate(span):
            for position, state in enumerate(STATES):
                amount = by_day.get(day, {}).get(state.value, 0)
                if amount:
                    height = max(1.0, (CHART_H - CHART_PAD) * amount / top)
                    chart.bars.append(
                        Bar(
                            x=f"{CHART_PAD + index * slot + position * bar_w * 1.1:.1f}",
                            y=f"{CHART_H - height:.1f}",
                            width=f"{bar_w:.1f}",
                            height=f"{height:.1f}",
                            state=state.value.lower(),
                        )
                    )
        parts = [f"{LABEL[s]} {chart.text(s.value)}" for s in STATES if chart.totals.get(s.value)]
        chart.summary = (
            f"{span[0].isoformat()} to {span[-1].isoformat()}. " + ", ".join(parts) + "."
        )
        charts.append(chart)
    charts.sort(key=lambda c: (-max(c.totals.values()), c.model))
    return charts, format_money(top, BILLING_CURRENCY)


# --- allocation and the queue ----------------------------------------------------


@dataclass(slots=True)
class AllocationRow:
    project: str
    team: str
    direct: int = 0
    inferred: int = 0
    manual: int = 0
    to_review: int = 0

    @property
    def total(self) -> int:
        return self.direct + self.inferred + self.manual

    def text(self, amount: int) -> str:
        return format_money(amount, BILLING_CURRENCY)


@dataclass(slots=True)
class AllocationTable:
    state: Finalization
    label: str
    rows: list[AllocationRow]
    allocated: int
    unmatched: int
    unallocated: int

    @property
    def record_total(self) -> int:
        return self.allocated + self.unmatched + self.unallocated

    def text(self, amount: int) -> str:
        return format_money(amount, BILLING_CURRENCY)

    def share_text(self, amount: int) -> str:
        return format_pct_bp(amount * 10_000 // self.record_total) if self.record_total else "0.00%"


def allocation_tables(
    conn: Connection, tenant_id: uuid.UUID, period: date
) -> list[AllocationTable]:
    f, n = allocation_facts, normalized_cost_records
    rows = conn.execute(
        select(n.c.finalization_state, f.c.project_id, f.c.state, f.c.confidence,
               func.sum(f.c.amount_micros).label("total"))
        .select_from(f.join(n, n.c.id == f.c.record_id))
        .where(f.c.tenant_id == tenant_id, f.c.is_current, n.c.is_current,
               n.c.billing_period == period, n.c.currency == BILLING_CURRENCY)
        .group_by(n.c.finalization_state, f.c.project_id, f.c.state, f.c.confidence)
    ).all()  # fmt: skip
    names = {
        r.id: (r.name, r.team)
        for r in conn.execute(
            select(projects.c.id, projects.c.name, org_units.c.name.label("team"))
            .select_from(projects.join(org_units, org_units.c.id == projects.c.team_id))
            .where(projects.c.tenant_id == tenant_id)
        )
    }
    tables = []
    for state in (Finalization.PROVIDER_REPORTED, Finalization.INVOICED):
        by_project: dict[uuid.UUID, AllocationRow] = {}
        loose = {"UNMATCHED": 0, "UNALLOCATED": 0}
        for r in rows:
            if r.finalization_state != state.value:
                continue
            if r.project_id is None:
                loose[r.state] += int(r.total)
                continue
            name, team = names.get(r.project_id, ("Unknown", ""))
            row = by_project.setdefault(r.project_id, AllocationRow(name, team))
            key = r.confidence.lower()
            setattr(row, key, getattr(row, key) + int(r.total))
            if r.state == "REVIEW":
                row.to_review += int(r.total)
        if by_project or any(loose.values()):
            ordered = sorted(by_project.values(), key=lambda a: a.project)
            tables.append(
                AllocationTable(state, LABEL[state], ordered, sum(a.total for a in ordered),
                                loose["UNMATCHED"], loose["UNALLOCATED"])
            )  # fmt: skip
    return tables


@dataclass(slots=True)
class QueueRow:
    record_id: uuid.UUID
    record_key: str
    charge_date: date
    model: str
    tags: list[tuple[str, str]]
    amount_text: str
    finalization: Finalization
    finalization_label: str
    state: str
    state_label: str
    join_confidence: int
    explanation: str
    suggested_project_id: uuid.UUID | None


def queue(conn: Connection, tenant_id: uuid.UUID, period: date) -> list[QueueRow]:
    f, n = allocation_facts, normalized_cost_records
    rows = conn.execute(
        select(n, f.c.state, f.c.join_confidence, f.c.explanation, f.c.project_id)
        .select_from(f.join(n, n.c.id == f.c.record_id))
        .where(f.c.tenant_id == tenant_id, f.c.is_current, n.c.is_current,
               n.c.billing_period == period, f.c.state.in_(QUEUE_STATES))
        .order_by(f.c.state, n.c.charge_date, n.c.record_key)
    ).all()  # fmt: skip
    return [
        QueueRow(
            record_id=r.id,
            record_key=r.record_key,
            charge_date=r.charge_date,
            model=r.model_id,
            tags=sorted(dict(r.tags).items()),
            amount_text=format_money(r.billed_micros, r.currency),
            finalization=Finalization(r.finalization_state),
            finalization_label=LABEL[Finalization(r.finalization_state)],
            state=r.state,
            state_label=QUEUE_LABEL[r.state],
            join_confidence=r.join_confidence,
            explanation=r.explanation,
            suggested_project_id=r.project_id,
        )
        for r in rows
    ]


@dataclass(slots=True)
class BatchRow:
    ingested_at: datetime
    file_name: str
    source_label: str
    status: str
    rows_total: int
    rows_new: int
    rows_revised: int
    rows_unchanged: int
    reasons: list[str]


def batches(conn: Connection, tenant_id: uuid.UUID, limit: int = 20) -> list[BatchRow]:
    b = ingestion_batches
    rows = conn.execute(
        select(b)
        .where(b.c.tenant_id == tenant_id)
        .order_by(b.c.ingested_at.desc(), b.c.id.desc())
        .limit(limit)
    )
    return [
        BatchRow(
            r.ingested_at, r.file_name,
            SOURCES[r.source].label if r.source in SOURCES else r.source,
            r.status, r.rows_total, r.rows_new, r.rows_revised, r.rows_unchanged, list(r.reasons),
        )
        for r in rows
    ]  # fmt: skip


def project_choices(conn: Connection, tenant_id: uuid.UUID) -> list[tuple[uuid.UUID, str]]:
    return [
        (r.id, r.name)
        for r in conn.execute(
            select(projects.c.id, projects.c.name)
            .where(projects.c.tenant_id == tenant_id)
            .order_by(projects.c.name)
        )
    ]


# --- reconciliation ------------------------------------------------------------------


@dataclass(slots=True)
class ReconRow:
    project: str
    estimated_text: str
    provider_text: str
    invoiced_text: str
    difference_text: str
    share_pct: int | None  # whole percent for the bar
    share_text: str
    uncontrolled_text: str | None
    has_provider: bool


@dataclass(slots=True)
class Reconciliation:
    rows: list[ReconRow]
    difference_text: str
    unattributed_text: str
    findings: int


def reconciliation(
    conn: Connection, tenant_id: uuid.UUID, period: date, totals: list[StateTotal]
) -> Reconciliation:
    lines = reconcile.project_lines(conn, tenant_id, period, BILLING_CURRENCY)
    money = lambda amount: format_money(amount, BILLING_CURRENCY)  # noqa: E731

    def signed(amount: int) -> str:
        return ("+" if amount > 0 else "-" if amount < 0 else "") + money(abs(amount))

    rows = []
    for line in lines:
        share = line.share_bp
        if share is None:
            share_text = "No provider data"
        elif share >= 10_000:
            # UX-8: never 100% unless the coverage badge is Enforced, which the MVP cannot reach.
            share_text = "99% or more. Not shown as 100%: egress is not verified"
        else:
            share_text = format_pct_bp(share)
        rows.append(
            ReconRow(
                project=line.project,
                estimated_text=money(line.estimated_micros),
                provider_text=money(line.provider_micros),
                invoiced_text=money(line.invoiced_micros),
                difference_text=signed(line.difference_micros)
                if line.provider_micros
                else "No provider data",
                share_pct=None if share is None else min(99, share // 100),
                share_text=share_text,
                uncontrolled_text=money(line.uncontrolled_micros)
                if line.uncontrolled_micros
                else None,
                has_provider=line.provider_micros > 0,
            )
        )
    estimated, provider = totals[0].figure.amount_micros, totals[1].figure.amount_micros
    tied = sum(line.provider_micros for line in lines)
    return Reconciliation(
        rows=rows,
        difference_text=signed(provider - estimated) if totals[1].has_data else "No provider data",
        unattributed_text=money(provider - tied) if totals[1].has_data else "No provider data",
        findings=sum(1 for r in rows if r.uncontrolled_text),
    )
