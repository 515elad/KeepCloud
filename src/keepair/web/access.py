"""Which permission each UI route needs (FR-13). The middleware refuses any route
that is not in this table, so a new route cannot be reachable by accident.

``tests/system/test_access.py`` checks that every registered route is listed and
walks every route as each role.
"""

from __future__ import annotations

from keepair.permissions import Perm

ROUTE_PERMS: dict[tuple[str, str], Perm] = {
    # No session needed.
    ("GET", "/healthz"): Perm.PUBLIC,
    ("GET", "/metrics"): Perm.PUBLIC,
    ("GET", "/login"): Perm.PUBLIC,
    ("POST", "/login"): Perm.PUBLIC,
    ("GET", "/login/code"): Perm.PUBLIC,
    ("POST", "/login/code"): Perm.PUBLIC,
    # Demo mode only, and only for a signed-in or half-signed-in demo user (checked inside).
    ("GET", "/api/demo-code"): Perm.PUBLIC,
    ("POST", "/logout"): Perm.VIEW,
    # Read-only pages.
    ("GET", "/"): Perm.VIEW,
    ("GET", "/budgets"): Perm.VIEW,
    ("GET", "/budgets/{budget_id}"): Perm.VIEW,
    ("GET", "/gateway"): Perm.VIEW,
    ("GET", "/gateway/fail-open"): Perm.VIEW,
    ("GET", "/api/fail-open"): Perm.VIEW,
    ("GET", "/spend"): Perm.VIEW,
    ("GET", "/reconciliation"): Perm.VIEW,
    ("GET", "/approvals"): Perm.VIEW,
    ("GET", "/reports"): Perm.VIEW,
    ("GET", "/{slug}"): Perm.VIEW,
    # Spend data.
    ("POST", "/spend/upload"): Perm.MANAGE_BILLING,
    ("POST", "/spend/assign"): Perm.MANAGE_BILLING,
    ("GET", "/reports/showback.csv"): Perm.EXPORT_REPORTS,
    # Gateway administration.
    ("POST", "/gateway/credentials"): Perm.MANAGE_CREDENTIALS,
    ("POST", "/gateway/credentials/{credential_id}/revoke"): Perm.MANAGE_CREDENTIALS,
    ("POST", "/gateway/fail-open/acknowledge"): Perm.ACK_FAIL_OPEN,
    ("GET", "/gateway/block"): Perm.BLOCK,
    ("POST", "/gateway/block"): Perm.BLOCK,
    ("GET", "/gateway/lift"): Perm.REQUEST_TWO_PERSON,
    ("POST", "/gateway/lift"): Perm.REQUEST_TWO_PERSON,
    # Budgets.
    ("POST", "/budgets/{budget_id}/owner"): Perm.MANAGE_BUDGETS,
    ("POST", "/budgets/{budget_id}/policy"): Perm.MANAGE_BUDGETS,
    # Approvals.
    ("POST", "/approvals/held/{reservation_id}"): Perm.DECIDE_HELD,
    ("POST", "/approvals/{approval_id}/decide"): Perm.DECIDE_TWO_PERSON,
    ("POST", "/approvals/{approval_id}/cancel"): Perm.CANCEL_REQUEST,
    # Admin.
    ("GET", "/admin"): Perm.VIEW_ADMIN,
    ("POST", "/admin/users"): Perm.MANAGE_USERS,
    ("POST", "/admin/users/{user_id}/status"): Perm.MANAGE_USERS,
    ("POST", "/admin/users/{user_id}/reset"): Perm.MANAGE_USERS,
    ("GET", "/admin/kill-switch"): Perm.KILL_SWITCH,
    ("POST", "/admin/kill-switch"): Perm.KILL_SWITCH,
    ("POST", "/admin/kill-switch/{switch_id}/off"): Perm.REQUEST_TWO_PERSON,
    ("POST", "/admin/demo/ledger"): Perm.DEMO_CONSOLE,
    ("POST", "/admin/demo/requests"): Perm.DEMO_CONSOLE,
    # Audit record.
    ("GET", "/audit-log"): Perm.VIEW_AUDIT,
    ("POST", "/audit-log/verify"): Perm.VERIFY_AUDIT,
}

# The permission needed to see each navigation page.
PAGE_PERMS: dict[str, Perm] = {
    "overview": Perm.VIEW,
    "spend": Perm.VIEW,
    "budgets": Perm.VIEW,
    "gateway": Perm.VIEW,
    "approvals": Perm.VIEW,
    "reconciliation": Perm.VIEW,
    "reports": Perm.VIEW,
    "admin": Perm.VIEW_ADMIN,
    "audit-log": Perm.VIEW_AUDIT,
}
