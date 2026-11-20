"""View models for the showback report and the audit record (phase 6)."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import Connection, func, select

from keepair.billing.finalization import Finalization
from keepair.billing.reconcile import period_bounds
from keepair.exports import Amount
from keepair.schema import audit_log, budgets, org_units, projects, usage_events, users
from keepair.web import spend_views
from keepair.web.formatting import format_money

CURRENCY = spend_views.BILLING_CURRENCY
SHARED = "Shared by the team"


@dataclass(slots=True)
class ShowbackRow:
    department: str
    team: str
    project: str
    owner: str
    estimated: int
    provider: int
    invoiced: int

    def text(self, amount: int) -> str:
        return format_money(amount, CURRENCY)


@dataclass(slots=True)
class Showback:
    period: date
    rows: list[ShowbackRow]
    estimated: int
    provider: int
    invoiced: int
    provider_loaded: bool
    invoiced_loaded: bool
    not_allocated: int  # provider-reported cost that no project carries yet

    def text(self, amount: int) -> str:
        return format_money(amount, CURRENCY)


def column_totals(rows: list[ShowbackRow]) -> tuple[int, int, int]:
    """Each column is summed on its own. Columns hold different states and are never added."""
    return (
        sum(r.estimated for r in rows),
        sum(r.provider for r in rows),
        sum(r.invoiced for r in rows),
    )


def showback(conn: Connection, tenant_id: uuid.UUID, period: date) -> Showback:
    """Cost per project for one month: what the gateway estimated, and what the
    provider reported and invoiced as allocated to the project (FR-12)."""
    start, end = period_bounds(period)
    u = usage_events
    estimated: dict[tuple[str, str | None], int] = {}
    for r in conn.execute(
        select(u.c.team, u.c.project, func.sum(u.c.price_micros).label("total"))
        .where(
            u.c.tenant_id == tenant_id, u.c.price_currency == CURRENCY,
            u.c.occurred_at >= start, u.c.occurred_at < end,
        )
        .group_by(u.c.team, u.c.project)
    ):  # fmt: skip
        estimated[(r.team or "", r.project)] = int(r.total or 0)
    tables = {t.state: t for t in spend_views.allocation_tables(conn, tenant_id, period)}
    provider = tables.get(Finalization.PROVIDER_REPORTED)
    invoiced = tables.get(Finalization.INVOICED)
    allocated = {
        state: {row.project: row.total for row in table.rows} if table else {}
        for state, table in ((Finalization.PROVIDER_REPORTED, provider),
                             (Finalization.INVOICED, invoiced))
    }  # fmt: skip
    unit = {
        r.id: r for r in conn.execute(select(org_units).where(org_units.c.tenant_id == tenant_id))
    }
    owner_by_scope = {
        r.scope_id: r.display_name
        for r in conn.execute(
            select(budgets.c.scope_id, users.c.display_name)
            .select_from(budgets.join(users, users.c.id == budgets.c.owner_user_id))
            .where(budgets.c.tenant_id == tenant_id, users.c.status == "ACTIVE")
        )
    }
    rows: list[ShowbackRow] = []
    for p in conn.execute(select(projects).where(projects.c.tenant_id == tenant_id)):
        team = unit.get(p.team_id)
        dept = unit.get(team.parent_id) if team is not None else None
        team_name = team.name if team is not None else ""
        rows.append(
            ShowbackRow(
                department=dept.name if dept is not None else "",
                team=team_name,
                project=p.name,
                owner=owner_by_scope.get(p.id, "Unowned"),
                estimated=estimated.get((team_name, p.name), 0),
                provider=allocated[Finalization.PROVIDER_REPORTED].get(p.name, 0),
                invoiced=allocated[Finalization.INVOICED].get(p.name, 0),
            )
        )
    for (team_name, project), amount in estimated.items():
        if project is None and amount:
            team = next((t for t in unit.values() if t.name == team_name), None)
            dept = unit.get(team.parent_id) if team is not None else None
            rows.append(
                ShowbackRow(
                    department=dept.name if dept is not None else "",
                    team=team_name,
                    project=SHARED,
                    owner=owner_by_scope.get(team.id, "Unowned") if team is not None else "Unowned",
                    estimated=amount, provider=0, invoiced=0,
                )
            )  # fmt: skip
    rows.sort(key=lambda r: (r.department, r.team, r.project == SHARED, r.project))
    est, prov, inv = column_totals(rows)
    return Showback(
        period, rows, est, prov, inv, provider is not None, invoiced is not None,
        (provider.unmatched + provider.unallocated) if provider else 0,
    )  # fmt: skip


SHOWBACK_HEADER = [
    "Period", "Department", "Team", "Project", "Owner", "Currency",
    "Estimated (gateway, not a charge)", "Provider-reported (allocated)", "Invoiced (allocated)",
]  # fmt: skip


def showback_csv_rows(report: Showback) -> list[list]:
    period = report.period.strftime("%Y-%m")
    return [
        [period, r.department, r.team, r.project, r.owner, CURRENCY,
         Amount(r.estimated),
         Amount(r.provider) if report.provider_loaded else None,
         Amount(r.invoiced) if report.invoiced_loaded else None]
        for r in report.rows
    ]  # fmt: skip


# --- Audit record -------------------------------------------------------------------

PAGE_SIZE = 100


@dataclass(slots=True)
class AuditRow:
    seq: int
    occurred_at: datetime
    actor: str
    action: str
    subject: str
    reason: str | None
    before: str | None
    after: str | None
    hash_short: str


def _json(value) -> str | None:
    return None if value is None else json.dumps(value, sort_keys=True, ensure_ascii=False)


def audit_rows(
    conn: Connection, tenant_id: uuid.UUID, before: int | None = None
) -> tuple[list[AuditRow], int, int | None]:
    """Newest first. Returns (rows, total count, seq to pass for the next page)."""
    a = audit_log
    mine = (a.c.tenant_id == tenant_id) | a.c.tenant_id.is_(None)
    total = conn.execute(select(func.count()).select_from(a).where(mine)).scalar_one()
    query = select(a).where(mine).order_by(a.c.seq.desc()).limit(PAGE_SIZE + 1)
    if before is not None:
        query = query.where(a.c.seq < before)
    found = conn.execute(query).all()
    rows = [
        AuditRow(
            r.seq, r.occurred_at, r.actor, r.action, f"{r.subject_type} {r.subject_id}", r.reason,
            _json(r.before), _json(r.after), bytes(r.row_hash).hex()[:12],
        )
        for r in found[:PAGE_SIZE]
    ]  # fmt: skip
    return rows, total, rows[-1].seq if len(found) > PAGE_SIZE else None
