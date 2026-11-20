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
from datetime import date

from sqlalchemy import Connection, func, select

from keepair import budgets as B
from keepair.billing.ingest import ingest
from keepair.clock import Clock, to_iso
from keepair.coverage import coverage_state
from keepair.demo import billing as demo_billing
from keepair.health import COMPONENTS, health_status
from keepair.rng import DEMO_SEED, seeded_rng
from keepair.schema import app_meta, heartbeats, normalized_cost_records, projects
from keepair.web import spend_views, views
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


def _fail_open_report(conn: Connection) -> views.FailOpenReport:
    return views.load_fail_open_report(conn, _tenant(conn))


def _fail_open_banner(conn: Connection, clock: Clock) -> Evaluated:
    # No gateway status is involved in the seeded state: the ledger was never unreachable.
    state = views.FailOpenState(gateway_reachable=True)
    views.add_unacknowledged(conn, _tenant(conn), state)
    shown = "shown" if state.show_banner else "not shown"
    return Evaluated(
        inputs={
            "ledger_unreachable": "yes" if state.active else "no",
            "waiting_in_spool": str(state.waiting),
            "unacknowledged_events": str(state.unacknowledged),
        },
        result=f"{shown}, count {state.count}",
    )


def _fail_open_events(conn: Connection, clock: Clock) -> Evaluated:
    count = _fail_open_report(conn).events
    return Evaluated({"fail_open_event_records": str(count)}, str(count))


def _fail_open_unacknowledged(conn: Connection, clock: Clock) -> Evaluated:
    count = _fail_open_report(conn).unacknowledged
    return Evaluated({"records_without_acknowledgement": str(count)}, str(count))


def _console_limit_kind(conn: Connection, clock: Clock) -> Evaluated:
    tenant = _tenant(conn)
    all_budgets = B.load_budgets(conn, tenant)
    names = views.load_scope_names(conn, tenant)
    project = "Ticket Triage"
    budget = next(b for b in all_budgets.values() if names[b.scope_id] == project)
    policies = [views.POLICY_LABEL[x.policy] for x in B.constraint_path(budget, all_budgets)]
    return Evaluated(
        inputs={"project": project, "policies_on_path": ", ".join(policies)},
        result=views.limit_kinds(conn, tenant)[project],
    )


# --- Spend data (phase 4). The worked examples describe the demo data after the two demo
# billing files (usage export and invoice) are loaded, so they are loaded here first, inside
# the caller's transaction.

EXAMPLE_PERIOD = date(2026, 1, 1)
EXAMPLE_ALLOC_PROJECT = "Build Assistant"
EXAMPLE_RECON_PROJECT = "Lead Scoring"


def _with_billing(conn: Connection, clock: Clock) -> uuid.UUID:
    tenant = _tenant(conn)
    loaded = conn.execute(select(func.count()).select_from(normalized_cost_records)).scalar_one()
    if not loaded:
        files = demo_billing.generate()
        rng = seeded_rng(DEMO_SEED + 9)
        for source, name in (("vendor-a-usage", demo_billing.USAGE_FILE),
                             ("vendor-a-invoice", demo_billing.INVOICE_FILE)):  # fmt: skip
            ingest(conn, tenant_id=tenant, source=source, file_name=name, data=files[name],
                   actor="worked-example", clock=clock, rng=rng)  # fmt: skip
    return tenant


def _totals(conn: Connection, clock: Clock) -> list[spend_views.StateTotal]:
    return spend_views.state_totals(conn, _with_billing(conn, clock), EXAMPLE_PERIOD)


def _cost_state(index: int, source: str):
    def evaluate(conn: Connection, clock: Clock) -> Evaluated:
        total = _totals(conn, clock)[index]
        return Evaluated({"period": "2026-01", "records_from": source}, total.text)

    return evaluate


def _cost_model_chart(conn: Connection, clock: Clock) -> Evaluated:
    charts, top = spend_views.explorer(conn, _with_billing(conn, clock), EXAMPLE_PERIOD)
    chart = next(c for c in charts if c.model == "vendor-a/model-1")
    return Evaluated({"model": chart.model, "scale_top": top}, chart.summary)


def _allocation_row(conn: Connection, clock: Clock) -> spend_views.AllocationRow:
    tables = spend_views.allocation_tables(conn, _with_billing(conn, clock), EXAMPLE_PERIOD)
    return next(r for r in tables[0].rows if r.project == EXAMPLE_ALLOC_PROJECT)


def _alloc(part: str):
    def evaluate(conn: Connection, clock: Clock) -> Evaluated:
        row = _allocation_row(conn, clock)
        inputs = {"project": row.project, "state": "Provider-reported"}
        if part == "total":
            inputs |= {"direct": row.text(row.direct), "inferred": row.text(row.inferred),
                       "manual": row.text(row.manual)}  # fmt: skip
        return Evaluated(inputs, row.text(getattr(row, part)))

    return evaluate


def _queue_review(conn: Connection, clock: Clock) -> spend_views.QueueRow:
    rows = spend_views.queue(conn, _with_billing(conn, clock), EXAMPLE_PERIOD)
    return next(
        r for r in rows if r.state == "REVIEW" and r.finalization.value == "PROVIDER_REPORTED"
    )


def _queue_join_confidence(conn: Connection, clock: Clock) -> Evaluated:
    row = _queue_review(conn, clock)
    tags = ", ".join(f"{k}={v}" for k, v in row.tags)
    return Evaluated({"tags": tags}, str(row.join_confidence))


def _queue_state(conn: Connection, clock: Clock) -> Evaluated:
    row = _queue_review(conn, clock)
    return Evaluated({"join_confidence": str(row.join_confidence)}, row.state_label)


def _recon(conn: Connection, clock: Clock) -> tuple[spend_views.Reconciliation, list]:
    tenant = _with_billing(conn, clock)
    totals = spend_views.state_totals(conn, tenant, EXAMPLE_PERIOD)
    return spend_views.reconciliation(conn, tenant, EXAMPLE_PERIOD, totals), totals


def _recon_difference(conn: Connection, clock: Clock) -> Evaluated:
    recon, totals = _recon(conn, clock)
    return Evaluated(
        {"provider_reported": totals[1].text, "estimated": totals[0].text}, recon.difference_text
    )


def _recon_unattributed(conn: Connection, clock: Clock) -> Evaluated:
    recon, totals = _recon(conn, clock)
    return Evaluated({"provider_reported": totals[1].text}, recon.unattributed_text)


def _recon_findings(conn: Connection, clock: Clock) -> Evaluated:
    recon, _ = _recon(conn, clock)
    flagged = ", ".join(r.project for r in recon.rows if r.uncontrolled_text)
    return Evaluated({"flagged_projects": flagged}, str(recon.findings))


def _recon_row(conn: Connection, clock: Clock) -> spend_views.ReconRow:
    recon, _ = _recon(conn, clock)
    return next(r for r in recon.rows if r.project == EXAMPLE_RECON_PROJECT)


def _recon_share(conn: Connection, clock: Clock) -> Evaluated:
    row = _recon_row(conn, clock)
    return Evaluated({"project": row.project, "estimated": row.estimated_text,
                      "provider_reported": row.provider_text}, row.share_text)  # fmt: skip


def _recon_finding(conn: Connection, clock: Clock) -> Evaluated:
    row = _recon_row(conn, clock)
    inputs = {
        "project": row.project,
        "provider_reported": row.provider_text,
        "estimated": row.estimated_text,
    }
    return Evaluated(inputs, f"Uncontrolled, {row.uncontrolled_text}")


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
    "fail_open_banner": _fail_open_banner,
    "fail_open_events": _fail_open_events,
    "fail_open_unacknowledged": _fail_open_unacknowledged,
    "console_limit_kind": _console_limit_kind,
    "cost_estimated": _cost_state(0, "gateway usage records"),
    "cost_provider_reported": _cost_state(1, "vendor-a usage export"),
    "cost_invoiced": _cost_state(2, "vendor-a invoice"),
    "cost_model_chart": _cost_model_chart,
    "alloc_direct": _alloc("direct"),
    "alloc_inferred": _alloc("inferred"),
    "alloc_manual": _alloc("manual"),
    "alloc_total": _alloc("total"),
    "queue_join_confidence": _queue_join_confidence,
    "queue_state": _queue_state,
    "recon_difference": _recon_difference,
    "recon_unattributed": _recon_unattributed,
    "recon_findings": _recon_findings,
    "recon_share": _recon_share,
    "recon_finding": _recon_finding,
}
