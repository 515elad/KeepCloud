"""Who may do what (FR-13, SEC-14, SEC-15). One matrix, tested exhaustively.

A permission is checked for every route by one piece of middleware. A route
that names no permission is refused. Some actions also depend on the object
(the owner of a budget, the requester of an approval); those checks live in the
service functions and are named in the comments below.
"""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    ADMIN = "ADMIN"
    FINANCE = "FINANCE"
    ENGINEERING = "ENGINEERING"
    AUDITOR = "AUDITOR"


ROLE_LABEL = {
    Role.ADMIN: "Administrator",
    Role.FINANCE: "Finance",
    Role.ENGINEERING: "Engineering",
    Role.AUDITOR: "Auditor",
}


class Perm(StrEnum):
    PUBLIC = "public"  # no session: sign-in pages, liveness, metrics, static files
    VIEW = "view"  # the read-only pages
    VIEW_ADMIN = "view_admin"  # users and the kill switch
    VIEW_AUDIT = "view_audit"
    VERIFY_AUDIT = "verify_audit"
    EXPORT_REPORTS = "export_reports"
    MANAGE_BILLING = "manage_billing"  # load billing files, assign records by hand
    MANAGE_CREDENTIALS = "manage_credentials"
    ACK_FAIL_OPEN = "ack_fail_open"
    DECIDE_HELD = "decide_held"  # plus: not the owner of the requesting project
    BLOCK = "block"  # add a block: one step
    MANAGE_BUDGETS = "manage_budgets"  # assign an owner, change a policy
    REQUEST_TWO_PERSON = "request_two_person"
    DECIDE_TWO_PERSON = "decide_two_person"  # plus: not the requester
    CANCEL_REQUEST = "cancel_request"  # plus: only the requester; changes no policy
    KILL_SWITCH = "kill_switch"
    MANAGE_USERS = "manage_users"
    DEMO_CONSOLE = "demo_console"


_ALL = frozenset(Role)
_ADMIN = frozenset({Role.ADMIN})

MATRIX: dict[Perm, frozenset[Role]] = {
    Perm.PUBLIC: _ALL,
    Perm.VIEW: _ALL,
    Perm.VIEW_ADMIN: frozenset({Role.ADMIN, Role.AUDITOR}),
    Perm.VIEW_AUDIT: frozenset({Role.ADMIN, Role.AUDITOR}),
    Perm.VERIFY_AUDIT: frozenset({Role.ADMIN, Role.AUDITOR}),
    Perm.EXPORT_REPORTS: frozenset({Role.ADMIN, Role.FINANCE, Role.AUDITOR}),
    Perm.MANAGE_BILLING: frozenset({Role.ADMIN, Role.FINANCE}),
    Perm.MANAGE_CREDENTIALS: _ADMIN,
    Perm.ACK_FAIL_OPEN: _ADMIN,
    Perm.DECIDE_HELD: frozenset({Role.ADMIN, Role.FINANCE, Role.ENGINEERING}),
    Perm.BLOCK: _ADMIN,
    Perm.MANAGE_BUDGETS: _ADMIN,
    Perm.REQUEST_TWO_PERSON: _ADMIN,
    Perm.DECIDE_TWO_PERSON: _ADMIN,
    Perm.CANCEL_REQUEST: _ADMIN,
    Perm.KILL_SWITCH: _ADMIN,
    Perm.MANAGE_USERS: _ADMIN,
    Perm.DEMO_CONSOLE: _ADMIN,
}

# Actions that need a fresh authenticator code in the same request (SEC-13 step-up).
STEP_UP = frozenset(
    {
        Perm.BLOCK,
        Perm.MANAGE_BUDGETS,
        Perm.REQUEST_TWO_PERSON,
        Perm.DECIDE_TWO_PERSON,
        Perm.KILL_SWITCH,
        Perm.MANAGE_USERS,
    }
)


def allowed(role: Role | str, perm: Perm) -> bool:
    try:
        return Role(role) in MATRIX[perm]
    except (ValueError, KeyError):
        return False
