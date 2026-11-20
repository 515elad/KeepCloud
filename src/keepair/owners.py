"""Budget owners and policy changes (FR-17, FR-04).

A budget has at most one accountable human owner, who is an active user. A hard
limit cannot be switched on without one. The same rule is a database trigger
(migration 0006), so it holds whatever writes the row.

These functions apply a change at once. Whether a change first needs a second
administrator is decided in ``keepair.approvals``.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Connection, select, update

from keepair import audit
from keepair.budgets import ENFORCING
from keepair.clock import Clock
from keepair.registry import clean_reason
from keepair.schema import budgets, users

POLICIES = ("MONITOR", "SOFT", "HARD", "APPROVAL")


class OwnerError(ValueError):
    """A refused change. ``code`` is stable; the message is safe to show."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _budget(conn: Connection, tenant_id: uuid.UUID, budget_id: uuid.UUID):
    row = conn.execute(
        select(budgets)
        .where(budgets.c.id == budget_id, budgets.c.tenant_id == tenant_id)
        .with_for_update()
    ).one_or_none()
    if row is None:
        raise OwnerError("NOT_FOUND", "This budget does not exist.")
    return row


def active_user(conn: Connection, tenant_id: uuid.UUID, user_id: uuid.UUID | None):
    """The user row when it is an active person of this tenant, else None.

    An agent or service identity is never a user, so it can never be an owner.
    """
    if user_id is None:
        return None
    return conn.execute(
        select(users.c.id, users.c.username, users.c.display_name).where(
            users.c.id == user_id, users.c.tenant_id == tenant_id, users.c.status == "ACTIVE"
        )
    ).one_or_none()


def owner_change_needs_second_person(policy: str, current_owner: uuid.UUID | None) -> bool:
    """needs_second = the budget is a hard limit and already has an owner (FR-17)."""
    return policy == "HARD" and current_owner is not None


def policy_change_needs_second_person(old: str, new: str) -> bool:
    """needs_second = the change takes away a limit that stops spend (SEC-15)."""
    return old in ENFORCING and new not in ENFORCING


def check_owner_change(conn: Connection, tenant_id: uuid.UUID, budget_id, user_id):
    budget = _budget(conn, tenant_id, budget_id)
    owner = active_user(conn, tenant_id, user_id)
    if user_id is not None and owner is None:
        raise OwnerError("NOT_A_USER", "The owner must be an active user. An agent cannot own.")
    if owner is None and budget.policy == "HARD":
        raise OwnerError("NO_OWNER", "A hard limit needs an owner. Assign another person instead.")
    if budget.owner_user_id == user_id:
        raise OwnerError("NO_CHANGE", "This person already owns the budget.")
    return budget, owner


def apply_owner(
    conn: Connection, clock: Clock, *, tenant_id: uuid.UUID, budget_id: uuid.UUID,
    user_id: uuid.UUID | None, actor: str, actor_id: uuid.UUID | None, reason: str,
) -> None:  # fmt: skip
    budget, owner = check_owner_change(conn, tenant_id, budget_id, user_id)
    reason = clean_reason(reason)
    before = active_or_any_name(conn, budget.owner_user_id)
    conn.execute(
        update(budgets)
        .where(budgets.c.id == budget_id)
        .values(owner_user_id=user_id, version=budgets.c.version + 1)
    )
    audit.record(
        conn, clock, tenant_id=tenant_id, actor=actor, actor_id=actor_id,
        action="budget.owner_changed", subject_type="budget", subject_id=str(budget_id),
        before={"owner": before}, after={"owner": owner.username if owner else None},
        reason=reason,
    )  # fmt: skip


def active_or_any_name(conn: Connection, user_id: uuid.UUID | None) -> str | None:
    if user_id is None:
        return None
    return conn.execute(select(users.c.username).where(users.c.id == user_id)).scalar_one_or_none()


def check_policy_change(conn: Connection, tenant_id: uuid.UUID, budget_id, policy: str):
    budget = _budget(conn, tenant_id, budget_id)
    if policy not in POLICIES:
        raise OwnerError("BAD_POLICY", "Choose one of the listed policies.")
    if policy == budget.policy:
        raise OwnerError("NO_CHANGE", "The budget already has this policy.")
    if policy == "HARD" and active_user(conn, tenant_id, budget.owner_user_id) is None:
        raise OwnerError(
            "NO_OWNER", "A hard limit cannot be switched on without an active owner (FR-17)."
        )
    return budget


def apply_policy(
    conn: Connection, clock: Clock, *, tenant_id: uuid.UUID, budget_id: uuid.UUID, policy: str,
    actor: str, actor_id: uuid.UUID | None, reason: str,
) -> None:  # fmt: skip
    budget = check_policy_change(conn, tenant_id, budget_id, policy)
    reason = clean_reason(reason)
    fail_mode = "FAIL_CLOSED" if policy in ENFORCING else "FAIL_OPEN"
    conn.execute(
        update(budgets)
        .where(budgets.c.id == budget_id)
        .values(policy=policy, fail_mode=fail_mode, version=budgets.c.version + 1)
    )
    audit.record(
        conn, clock, tenant_id=tenant_id, actor=actor, actor_id=actor_id,
        action="budget.policy_changed", subject_type="budget", subject_id=str(budget_id),
        before={"policy": budget.policy, "fail_mode": budget.fail_mode},
        after={"policy": policy, "fail_mode": fail_mode}, reason=reason,
    )  # fmt: skip
