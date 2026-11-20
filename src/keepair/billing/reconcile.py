"""Reconciliation of gateway estimates with provider figures (FR-07), and
uncontrolled-spend detection (FR-19).

All amounts are in the billing currency. Gateway usage is compared through the
cost it recorded in the price list's currency, so no conversion happens here.

    Per project, only cost that the record's tags tie to that project is compared.

    difference              = provider_reported - estimated
    gateway_controlled_share = estimated / provider_reported   (at most 100%)
    uncontrolled            = difference, when it is above the greater of
                              2% of provider_reported and 1.00 currency unit
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import Connection, func, select

from keepair.money import MICRO_PER_UNIT
from keepair.schema import allocation_facts, normalized_cost_records, projects, usage_events
from keepair.web.formatting import period_end

THRESHOLD_BP = 200  # 2% of provider usage (proposed in PRD v1.4 FR-19, to be tuned in pilot)
THRESHOLD_MIN_MICROS = MICRO_PER_UNIT  # or one currency unit, whichever is larger


def uncontrolled_micros(provider_micros: int, gateway_micros: int) -> int:
    """The amount the provider saw beyond what the gateway recorded, if above the threshold."""
    delta = provider_micros - gateway_micros
    threshold = max(provider_micros * THRESHOLD_BP // 10_000, THRESHOLD_MIN_MICROS)
    return delta if delta > threshold else 0


def controlled_share_bp(provider_micros: int, gateway_micros: int) -> int | None:
    """Share of provider-reported usage that the gateway recorded. None without provider data."""
    if provider_micros <= 0:
        return None
    return min(10_000, gateway_micros * 10_000 // provider_micros)


@dataclass(frozen=True, slots=True)
class ProjectLine:
    project_id: uuid.UUID
    project: str
    estimated_micros: int
    provider_micros: int
    invoiced_micros: int

    @property
    def difference_micros(self) -> int:
        return self.provider_micros - self.estimated_micros

    @property
    def uncontrolled_micros(self) -> int:
        return uncontrolled_micros(self.provider_micros, self.estimated_micros)

    @property
    def share_bp(self) -> int | None:
        return controlled_share_bp(self.provider_micros, self.estimated_micros)


def period_bounds(period: date) -> tuple[datetime, datetime]:
    start = datetime(period.year, period.month, 1, tzinfo=timezone.utc)  # noqa: UP017
    end_day = period_end("MONTH", period) + timedelta(days=1)
    return start, datetime(end_day.year, end_day.month, end_day.day, tzinfo=timezone.utc)  # noqa: UP017


def project_lines(
    conn: Connection, tenant_id: uuid.UUID, period: date, currency: str
) -> list[ProjectLine]:
    start, end = period_bounds(period)
    u, f, n = usage_events, allocation_facts, normalized_cost_records
    estimated = dict(
        conn.execute(
            select(u.c.project, func.coalesce(func.sum(u.c.price_micros), 0))
            .where(
                u.c.tenant_id == tenant_id, u.c.price_currency == currency,
                u.c.occurred_at >= start, u.c.occurred_at < end, u.c.project.is_not(None),
            )
            .group_by(u.c.project)
        ).all()
    )  # fmt: skip
    # Only cost that the tags tie to the project itself. Shared cost that a rule splits
    # between projects has no per-project gateway record to compare with.
    total = func.sum(f.c.amount_micros).label("total")
    billed: dict[tuple[uuid.UUID, str], int] = {
        (r.project_id, r.finalization_state): int(r.total)
        for r in conn.execute(
            select(f.c.project_id, n.c.finalization_state, total)
            .select_from(f.join(n, n.c.id == f.c.record_id))
            .where(
                f.c.tenant_id == tenant_id, f.c.is_current, n.c.is_current,
                f.c.project_id.is_not(None), f.c.rule_id.is_(None),
                n.c.billing_period == period, n.c.currency == currency,
            )
            .group_by(f.c.project_id, n.c.finalization_state)
        )
    }  # fmt: skip
    rows = conn.execute(
        select(projects.c.id, projects.c.name)
        .where(projects.c.tenant_id == tenant_id)
        .order_by(projects.c.name)
    )
    return [
        ProjectLine(
            r.id, r.name, int(estimated.get(r.name, 0)),
            billed.get((r.id, "PROVIDER_REPORTED"), 0), billed.get((r.id, "INVOICED"), 0),
        )
        for r in rows
    ]  # fmt: skip


def uncontrolled_projects(
    conn: Connection, tenant_id: uuid.UUID, currency: str = "USD"
) -> set[uuid.UUID]:
    """Projects with an uncontrolled-spend finding in any period that has provider data."""
    n = normalized_cost_records
    periods = conn.execute(
        select(n.c.billing_period).where(n.c.tenant_id == tenant_id, n.c.is_current).distinct()
    ).scalars()
    found: set[uuid.UUID] = set()
    for period in periods:
        found |= {
            line.project_id
            for line in project_lines(conn, tenant_id, period, currency)
            if line.uncontrolled_micros
        }
    return found
