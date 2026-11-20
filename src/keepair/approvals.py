"""Decisions by people (FR-11, SEC-15, UX-11).

Two kinds of decision live here.

**Held requests.** A request on an approval budget is held: budget is reserved,
nothing is sent, and the request body is not stored (D-07). Approving keeps the
reservation for one matching resubmission within 15 minutes (UX-D2). Rejecting
or letting it expire releases the budget. The owner of the requesting project
is the requesting side and cannot approve.

**Two-person actions.** Lifting a block, switching a kill switch off, changing
the owner of a hard-limit budget and weakening an enforcing budget are requested
by one administrator and take effect only when a different administrator
approves within 24 hours. The approver gives a fresh authenticator code; the
route checks that before calling ``decide``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import Connection, func, insert, select, update

from keepair import audit, killswitch, owners, registry
from keepair.clock import Clock
from keepair.gateway import ledger
from keepair.ids import uuid7
from keepair.permissions import Role
from keepair.rng import Rng
from keepair.schema import agents, approvals, budgets, kill_switches, reservations, users

TWO_PERSON_KINDS = ("BLOCK_LIFT", "KILL_SWITCH_OFF", "OWNER_CHANGE", "POLICY_CHANGE")
EXPIRY_S = 24 * 3600
RESUBMIT_WINDOW_S = 15 * 60
KIND_LABEL = {
    "HELD_REQUEST": "Held request",
    "BLOCK_LIFT": "Lift a block",
    "KILL_SWITCH_OFF": "Switch a kill switch off",
    "OWNER_CHANGE": "Change the owner of a hard-limit budget",
    "POLICY_CHANGE": "Weaken an enforcing budget",
}


class ApprovalError(ValueError):
    """A refused decision. ``code`` is stable; the message is safe to show."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def may_decide(requested_by: uuid.UUID | None, actor_id: uuid.UUID, actor_role: str) -> bool:
    """may_decide = the actor is an administrator and is not the requester (SEC-15)."""
    return actor_role == Role.ADMIN and requested_by != actor_id


# --- Two-person actions -----------------------------------------------------------


def request(
    conn: Connection, clock: Clock, rng: Rng, *, tenant_id: uuid.UUID, kind: str,
    subject_type: str, subject_id: str, summary: str, payload: dict, actor, reason: str,
) -> uuid.UUID:  # fmt: skip
    if kind not in TWO_PERSON_KINDS:
        raise ApprovalError("BAD_KIND", "Unknown kind of request.")
    reason = registry.clean_reason(reason)
    expire_due(conn, clock, tenant_id)
    a = approvals
    waiting = conn.execute(
        select(a.c.id).where(
            a.c.tenant_id == tenant_id, a.c.kind == kind, a.c.subject_type == subject_type,
            a.c.subject_id == subject_id, a.c.decision.is_(None),
        )
    ).first()  # fmt: skip
    if waiting is not None:
        raise ApprovalError("ALREADY_PENDING", "A request for this is already waiting.")
    approval_id, now = uuid7(clock, rng), clock.now()
    conn.execute(
        insert(a).values(
            id=approval_id, tenant_id=tenant_id, kind=kind, subject_type=subject_type,
            subject_id=subject_id, summary=summary, payload=payload, requested_by=actor.id,
            requested_by_name=actor.username, requested_at=now, reason=reason,
            expires_at=now + timedelta(seconds=EXPIRY_S),
        )
    )  # fmt: skip
    audit.record(
        conn, clock, tenant_id=tenant_id, actor=actor.username, actor_id=actor.id,
        action=f"{kind.lower()}.requested", subject_type=subject_type, subject_id=subject_id,
        after={"approval_id": str(approval_id), "summary": summary}, reason=reason,
    )  # fmt: skip
    return approval_id


def expire_due(conn: Connection, clock: Clock, tenant_id: uuid.UUID) -> int:
    """Close two-person requests nobody confirmed within 24 hours. Nothing is changed by them."""
    a = approvals
    due = conn.execute(
        select(a.c.id, a.c.kind, a.c.subject_type, a.c.subject_id)
        .where(a.c.tenant_id == tenant_id, a.c.decision.is_(None), a.c.expires_at <= clock.now())
        .with_for_update()
    ).all()
    for row in due:
        conn.execute(
            update(a).where(a.c.id == row.id).values(decision="EXPIRED", decided_at=clock.now())
        )
        audit.record(
            conn, clock, tenant_id=tenant_id, actor="system", action=f"{row.kind.lower()}.expired",
            subject_type=row.subject_type, subject_id=row.subject_id,
            after={"approval_id": str(row.id)},
        )  # fmt: skip
    return len(due)


def _execute(conn: Connection, clock: Clock, row, approver) -> None:
    both = f"{row.requested_by_name} + {approver.username}"
    payload = row.payload
    if row.kind == "BLOCK_LIFT":
        registry.lift_block(
            conn, row.tenant_id, row.subject_type, row.subject_id, both, row.reason, clock
        )
        audit.record(
            conn, clock, tenant_id=row.tenant_id, actor=both, actor_id=approver.id,
            action="registry.unblocked", subject_type=row.subject_type, subject_id=row.subject_id,
            before={"status": "BLOCKED"}, after={"status": "ALLOWED"}, reason=row.reason,
        )  # fmt: skip
    elif row.kind == "KILL_SWITCH_OFF":
        killswitch.deactivate(
            conn, clock, tenant_id=row.tenant_id, switch_id=uuid.UUID(row.subject_id),
            actor=both, actor_id=approver.id, reason=row.reason,
        )  # fmt: skip
    elif row.kind == "OWNER_CHANGE":
        owners.apply_owner(
            conn, clock, tenant_id=row.tenant_id, budget_id=uuid.UUID(row.subject_id),
            user_id=uuid.UUID(payload["user_id"]) if payload.get("user_id") else None,
            actor=both, actor_id=approver.id, reason=row.reason,
        )  # fmt: skip
    elif row.kind == "POLICY_CHANGE":
        owners.apply_policy(
            conn, clock, tenant_id=row.tenant_id, budget_id=uuid.UUID(row.subject_id),
            policy=payload["policy"], actor=both, actor_id=approver.id, reason=row.reason,
        )  # fmt: skip


def decide(
    conn: Connection, clock: Clock, *, tenant_id: uuid.UUID, approval_id: uuid.UUID, actor,
    approve: bool,
) -> str:  # fmt: skip
    """Approve or reject a two-person request. Returns the decision."""
    a = approvals
    row = conn.execute(
        select(a).where(a.c.id == approval_id, a.c.tenant_id == tenant_id).with_for_update()
    ).one_or_none()
    if row is None or row.kind not in TWO_PERSON_KINDS or row.decision is not None:
        raise ApprovalError("NOT_PENDING", "This request is not waiting for a decision.")
    if row.expires_at <= clock.now():
        raise ApprovalError("EXPIRED", "This request was not confirmed within 24 hours.")
    if row.requested_by == actor.id:
        raise ApprovalError(
            "SELF_APPROVAL", "You made this request. A different administrator must decide it."
        )
    if not may_decide(row.requested_by, actor.id, actor.role):
        raise ApprovalError("NOT_ELIGIBLE", "Only an administrator can decide this request.")
    decision = "APPROVED" if approve else "REJECTED"
    if approve:
        try:
            _execute(conn, clock, row, actor)
        except (registry.RegistryError, killswitch.KillSwitchError, owners.OwnerError) as exc:
            raise ApprovalError("CANNOT_APPLY", str(exc)) from None
    conn.execute(
        update(a)
        .where(a.c.id == approval_id)
        .values(decision=decision, decided_by=actor.id, decided_by_name=actor.username,
                decided_at=clock.now())
    )  # fmt: skip
    audit.record(
        conn, clock, tenant_id=tenant_id, actor=actor.username, actor_id=actor.id,
        action=f"{row.kind.lower()}.{decision.lower()}", subject_type=row.subject_type,
        subject_id=row.subject_id,
        after={"approval_id": str(approval_id), "requested_by": row.requested_by_name},
    )  # fmt: skip
    return decision


def cancel(
    conn: Connection, clock: Clock, *, tenant_id: uuid.UUID, approval_id: uuid.UUID, actor
) -> None:
    """The requester withdraws a request that nobody has decided."""
    a = approvals
    row = conn.execute(
        select(a).where(a.c.id == approval_id, a.c.tenant_id == tenant_id).with_for_update()
    ).one_or_none()
    if row is None or row.kind not in TWO_PERSON_KINDS or row.decision is not None:
        raise ApprovalError("NOT_PENDING", "This request is not waiting for a decision.")
    if row.requested_by != actor.id:
        raise ApprovalError("NOT_REQUESTER", "Only the person who made the request can cancel it.")
    conn.execute(
        update(a)
        .where(a.c.id == approval_id)
        .values(decision="CANCELLED", decided_by=actor.id, decided_by_name=actor.username,
                decided_at=clock.now())
    )  # fmt: skip
    audit.record(
        conn, clock, tenant_id=tenant_id, actor=actor.username, actor_id=actor.id,
        action=f"{row.kind.lower()}.cancelled", subject_type=row.subject_type,
        subject_id=row.subject_id, after={"approval_id": str(approval_id)},
    )  # fmt: skip


def eligible_approvers(
    conn: Connection, tenant_id: uuid.UUID, requested_by: uuid.UUID | None
) -> list[str]:
    """Active administrators other than the requester."""
    rows = conn.execute(
        select(users.c.id, users.c.username)
        .where(users.c.tenant_id == tenant_id, users.c.status == "ACTIVE", users.c.role == "ADMIN")
        .order_by(users.c.username)
    )
    return [r.username for r in rows if r.id != requested_by]


# --- Requests that may or may not need a second person ------------------------------


def request_block_lift(conn, clock, rng, *, tenant_id, subject_type, subject_id, actor, reason):
    if registry.subject_status(conn, tenant_id, subject_type, subject_id) != "BLOCKED":
        raise ApprovalError("NOT_BLOCKED", "This item is not blocked.")
    return request(
        conn, clock, rng, tenant_id=tenant_id, kind="BLOCK_LIFT", subject_type=subject_type,
        subject_id=subject_id, summary=f"Lift the block on {subject_type} {subject_id}",
        payload={}, actor=actor, reason=reason,
    )  # fmt: skip


def request_kill_switch_off(conn, clock, rng, *, tenant_id, switch_id, actor, reason):
    k = kill_switches
    row = conn.execute(
        select(k.c.scope_name).where(
            k.c.id == switch_id, k.c.tenant_id == tenant_id, k.c.deactivated_at.is_(None)
        )
    ).one_or_none()
    if row is None:
        raise ApprovalError("NOT_ON", "This kill switch is not on.")
    return request(
        conn, clock, rng, tenant_id=tenant_id, kind="KILL_SWITCH_OFF", subject_type="kill_switch",
        subject_id=str(switch_id), summary=f"Switch off the kill switch on {row.scope_name}",
        payload={}, actor=actor, reason=reason,
    )  # fmt: skip


def change_owner(conn, clock, rng, *, tenant_id, budget_id, budget_name, user_id, actor, reason):
    """Assign an owner. Returns None when applied at once, or the approval ID when a
    second administrator must confirm (FR-17: owner change on an active hard limit)."""
    try:
        budget, owner = owners.check_owner_change(conn, tenant_id, budget_id, user_id)
        if not owners.owner_change_needs_second_person(budget.policy, budget.owner_user_id):
            owners.apply_owner(
                conn, clock, tenant_id=tenant_id, budget_id=budget_id, user_id=user_id,
                actor=actor.username, actor_id=actor.id, reason=reason,
            )  # fmt: skip
            return None
    except owners.OwnerError as exc:
        raise ApprovalError(exc.code, str(exc)) from None
    return request(
        conn, clock, rng, tenant_id=tenant_id, kind="OWNER_CHANGE", subject_type="budget",
        subject_id=str(budget_id),
        summary=f"Make {owner.username} the owner of the {budget_name} budget",
        payload={"user_id": str(user_id)}, actor=actor, reason=reason,
    )  # fmt: skip


def change_policy(conn, clock, rng, *, tenant_id, budget_id, budget_name, policy, actor, reason):
    """Change a policy. Returns None when applied at once, or the approval ID when a
    second administrator must confirm (the change removes a limit that stops spend)."""
    try:
        budget = owners.check_policy_change(conn, tenant_id, budget_id, policy)
        if not owners.policy_change_needs_second_person(budget.policy, policy):
            owners.apply_policy(
                conn, clock, tenant_id=tenant_id, budget_id=budget_id, policy=policy,
                actor=actor.username, actor_id=actor.id, reason=reason,
            )  # fmt: skip
            return None
    except owners.OwnerError as exc:
        raise ApprovalError(exc.code, str(exc)) from None
    return request(
        conn, clock, rng, tenant_id=tenant_id, kind="POLICY_CHANGE", subject_type="budget",
        subject_id=str(budget_id),
        summary=f"Change the {budget_name} budget from {budget.policy} to {policy}",
        payload={"policy": policy}, actor=actor, reason=reason,
    )  # fmt: skip


# --- Held requests ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HeldDecision:
    reservation_id: uuid.UUID
    decision: str
    resubmit_until: object | None


def held_eligibility(
    actor_id: uuid.UUID, actor_role: str, own_budget_owner: uuid.UUID | None,
    path_owners: list[uuid.UUID | None],
) -> str | None:  # fmt: skip
    """Why this person cannot decide a held request, or None when they can.

    The owner of the requesting project's budget is the requesting side. An
    approver is an administrator, or the owner of a budget above it on the limit path.
    """
    if own_budget_owner == actor_id:
        return "SELF_APPROVAL"
    if actor_role == Role.ADMIN or actor_id in path_owners:
        return None
    return "NOT_ELIGIBLE"


def decide_held(
    conn: Connection, clock: Clock, rng: Rng, *, tenant_id: uuid.UUID,
    reservation_id: uuid.UUID, actor, approve: bool, note: str = "",
) -> HeldDecision:  # fmt: skip
    r = reservations
    row = conn.execute(
        select(r, (r.c.expires_at > func.now()).label("live"))
        .where(r.c.id == reservation_id, r.c.tenant_id == tenant_id)
        .with_for_update()
    ).one_or_none()
    if row is None or row.state != "HELD" or not row.live:
        raise ApprovalError("NOT_PENDING", "This request is not waiting for a decision.")
    owner_of = dict(
        conn.execute(
            select(budgets.c.id, budgets.c.owner_user_id).where(
                budgets.c.id.in_(list(row.budget_path))
            )
        ).all()
    )
    above = [owner_of.get(b) for b in row.budget_path if b != row.budget_id]
    problem = held_eligibility(actor.id, actor.role, owner_of.get(row.budget_id), above)
    if problem == "SELF_APPROVAL":
        raise ApprovalError(
            "SELF_APPROVAL",
            "This request comes from your own project. Someone else must decide it.",
        )
    if problem:
        raise ApprovalError(
            "NOT_ELIGIBLE",
            "Only an administrator or the owner of a budget above this project can decide.",
        )
    note = " ".join(note.split())[:300]
    agent = conn.execute(
        select(agents.c.name).where(agents.c.id == row.agent_id)
    ).scalar_one_or_none()
    until = None
    if approve:
        until = conn.execute(
            update(r)
            .where(r.c.id == reservation_id)
            .values(
                state="APPROVED",
                # Database clock, like every reservation expiry (SEC-35).
                expires_at=func.now() + func.make_interval(0, 0, 0, 0, 0, 0, RESUBMIT_WINDOW_S),
            )
            .returning(r.c.expires_at)
        ).scalar_one()
    else:
        ledger.release(conn, reservation_id, clock=clock)
    decision = "APPROVED" if approve else "REJECTED"
    conn.execute(
        insert(approvals).values(
            id=uuid7(clock, rng), tenant_id=tenant_id, kind="HELD_REQUEST",
            subject_type="reservation", subject_id=str(reservation_id),
            summary=f"{agent or 'Unknown agent'} asked for {row.model_id or 'a model'}",
            payload={"reserved_micros": row.reserved_micros, "currency": row.currency},
            requested_by=None, requested_by_name=agent or "Unknown agent",
            requested_at=row.created_at, reason=note, expires_at=row.expires_at,
            decision=decision, decided_by=actor.id, decided_by_name=actor.username,
            decided_at=clock.now(),
        )
    )  # fmt: skip
    audit.record(
        conn, clock, tenant_id=tenant_id, actor=actor.username, actor_id=actor.id,
        action=f"held_request.{decision.lower()}", subject_type="reservation",
        subject_id=str(reservation_id),
        after={"agent": agent, "model": row.model_id, "reserved_micros": row.reserved_micros,
               "currency": row.currency},
        reason=note or None,
    )  # fmt: skip
    return HeldDecision(reservation_id, decision, until)
