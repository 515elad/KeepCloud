"""Formula functions named by the help registry.

Each calculated field in ui/help/field_help.yaml names one entry here through
``formula_fn``. An entry runs the real function on the demo record used in the
registry's worked example and returns the inputs and the result as the display
strings the registry shows. A test compares the two, so the help text cannot
drift from the code.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import Connection, select

from keepair import budgets as B
from keepair.clock import Clock, to_iso
from keepair.coverage import coverage_state
from keepair.health import COMPONENTS, health_status
from keepair.schema import app_meta, heartbeats, projects
from keepair.web import views
from keepair.web.formatting import format_money

EXAMPLE_PROJECT = "Research Agent"
EXAMPLE_MODEL = "vendor-b/model-1"
EXAMPLE_BLOCK_VENDOR = "vendor-a"
EXAMPLE_REASON = "VENDOR_BLOCKED"


@dataclass(frozen=True, slots=True)
class Evaluated:
    inputs: dict[str, str]
    result: str


def _tenant(conn: Connection) -> uuid.UUID:
    value = conn.execute(select(app_meta.c.value).where(app_meta.c.key == "tenant_id")).scalar_one()
    return uuid.UUID(value)


def _health_status(conn: Connection, clock: Clock) -> Evaluated:
    component = COMPONENTS[0]
    last = conn.execute(
        select(heartbeats.c.last_heartbeat_at).where(heartbeats.c.component == component.id)
    ).scalar_one_or_none()
    now = clock.now()
    status = health_status(last, now, component.degraded_after_s, component.failing_after_s)
    return Evaluated(
        inputs={
            "component": component.id,
            "last_heartbeat_at": to_iso(last) if last else "none",
            "now": to_iso(now),
            "degraded_after_s": str(component.degraded_after_s),
            "failing_after_s": str(component.failing_after_s),
        },
        result=status.value,
    )


def _example_budget(conn: Connection) -> tuple[B.Budget, dict[uuid.UUID, B.Budget], dict]:
    tenant = _tenant(conn)
    all_budgets = B.load_budgets(conn, tenant)
    names = views.load_scope_names(conn, tenant)
    budget = next(b for b in all_budgets.values() if names[b.scope_id] == EXAMPLE_PROJECT)
    return budget, all_budgets, names


def _money_inputs(b: B.Budget) -> dict[str, str]:
    return {
        "cap": format_money(b.cap_micros, b.currency),
        "committed": format_money(b.committed_micros, b.currency),
        "reserved": format_money(b.reserved_micros, b.currency),
    }


def _budget_remaining(conn: Connection, clock: Clock) -> Evaluated:
    b, _, _ = _example_budget(conn)
    return Evaluated(_money_inputs(b), format_money(B.remaining(b), b.currency))


def _budget_usage(conn: Connection, clock: Clock) -> Evaluated:
    b, _, _ = _example_budget(conn)
    return Evaluated(_money_inputs(b), views._bar(b).summary)


def _budget_enforcing(conn: Connection, clock: Clock) -> Evaluated:
    b, _, _ = _example_budget(conn)
    return Evaluated({"policy": views.POLICY_LABEL[b.policy]}, "Yes" if b.enforcing else "No")


def _budget_effective_remaining(conn: Connection, clock: Clock) -> Evaluated:
    b, all_budgets, names = _example_budget(conn)
    eff = B.effective_remaining(b, all_budgets)
    inputs = {
        f"remaining({names[x.scope_id]}, {views.POLICY_LABEL[x.policy]})": (
            format_money(B.remaining(x), x.currency) if x.enforcing else "not limiting"
        )
        for x in eff.path
    }
    return Evaluated(inputs, format_money(eff.amount_micros, b.currency))


def _coverage_state(conn: Connection, clock: Clock) -> Evaluated:
    p = conn.execute(select(projects).where(projects.c.name == EXAMPLE_PROJECT)).one()
    yes_no = {True: "yes", False: "no"}
    return Evaluated(
        inputs={
            "project": p.name,
            "key_custody": p.key_custody,
            "egress_verified": yes_no[p.egress_verified],
            "uncontrolled_finding": "no",
        },
        result=coverage_state(p.key_custody, p.egress_verified, False).value,
    )


def _model_effective_status(conn: Connection, clock: Clock) -> Evaluated:
    registry = views.load_registry(conn, _tenant(conn))
    model = next(m for m in registry.models if m.id == EXAMPLE_MODEL)
    vendor = next(v for v in registry.vendors if v.id == model.vendor_id)
    label = {
        "ALLOWED": "Allowed",
        "BLOCKED": "Blocked",
        "BLOCKED_BY_VENDOR": f"Blocked by vendor {vendor.id}",
    }[model.effective.value]
    return Evaluated(
        inputs={
            "model": model.id,
            "vendor_status": vendor.status.value,
            "model_status": model.own_status.value,
        },
        result=label,
    )


def _block_impact(conn: Connection, clock: Clock) -> Evaluated:
    registry = views.load_registry(conn, _tenant(conn))
    affected = [m.id for m in registry.models if m.vendor_id == EXAMPLE_BLOCK_VENDOR]
    return Evaluated({"subject": f"vendor {EXAMPLE_BLOCK_VENDOR}"}, ", ".join(affected))


def _activity(conn: Connection, clock: Clock) -> views.Activity:
    return views.load_activity(conn, _tenant(conn), clock.now())


def _gateway_requests(conn: Connection, clock: Clock) -> Evaluated:
    count = _activity(conn, clock).requests
    return Evaluated({"decision_records_in_window": str(count)}, str(count))


def _gateway_refused(conn: Connection, clock: Clock) -> Evaluated:
    count = _activity(conn, clock).refused
    return Evaluated({"denied_records_in_window": str(count)}, str(count))


def _gateway_held(conn: Connection, clock: Clock) -> Evaluated:
    count = _activity(conn, clock).held
    return Evaluated({"held_records_in_window": str(count)}, str(count))


def _denial_count(conn: Connection, clock: Clock) -> Evaluated:
    summary = {r.code: r for r in _activity(conn, clock).reasons}.get(EXAMPLE_REASON)
    return Evaluated({"reason": EXAMPLE_REASON}, str(summary.count if summary else 0))


def _denial_trend(conn: Connection, clock: Clock) -> Evaluated:
    summary = {r.code: r for r in _activity(conn, clock).reasons}.get(EXAMPLE_REASON)
    peak = summary.peak if summary else 0
    return Evaluated({"reason": EXAMPLE_REASON}, f"at most {peak} in one hour")


def _credential_status(conn: Connection, clock: Clock) -> Evaluated:
    agent = "research-agent"
    row = next(r for r in views.load_credentials(conn, _tenant(conn)).rows if r.agent == agent)
    lifetime_days = (row.expires_at - row.created_at).days
    return Evaluated(
        inputs={
            "agent": row.agent,
            "revoked_at": "none" if row.revoked_at is None else "set",
            "expires_at": f"{lifetime_days} days after it was issued",
        },
        result=row.status,
    )


FORMULAS: dict[str, Callable[[Connection, Clock], Evaluated]] = {
    "health_status": _health_status,
    "coverage_state": _coverage_state,
    "budget_remaining": _budget_remaining,
    "budget_usage": _budget_usage,
    "budget_enforcing": _budget_enforcing,
    "budget_effective_remaining": _budget_effective_remaining,
    "model_effective_status": _model_effective_status,
    "block_impact": _block_impact,
    "gateway_requests": _gateway_requests,
    "gateway_refused": _gateway_refused,
    "gateway_held": _gateway_held,
    "denial_count": _denial_count,
    "denial_trend": _denial_trend,
    "credential_status": _credential_status,
}
