# Phase 5: Owners, approvals and two-person actions

Lifecycle record, aligned with ISO/IEC 12207 (plan, entry and exit criteria, review).

## Plan

**Scope.**

- Local user accounts with a password and TOTP as a second factor (FR-13, FR-17). Every page needs a signed-in session. Roles ADMIN, FINANCE, ENGINEERING, AUDITOR; a permission matrix in code decides which role may use which route, and a route with no entry is refused.
- Step-up: actions that change policy ask for a fresh authenticator code in the same form (SEC-13). A code is accepted once.
- Budget owners (FR-17): a budget has one accountable human owner. A hard limit cannot be switched on without an active owner, enforced in the service and by a database trigger. Unowned spend is shown on Overview.
- HELD queue (FR-11): an approver sees the held request's metadata, the budget impact and the expiry. Under D-07 the request body is not stored, so approving allows one matching resubmission within 15 minutes, and the button says so (UX-D2). The owner of the requesting project cannot approve its requests.
- Two-person actions (SEC-15, UX-11): lifting a block, switching a kill switch off, changing the owner of a hard-limit budget, and weakening an enforcing budget. The second person must be a different administrator, must give a fresh authenticator code, and must confirm within 24 hours.
- Kill switch (FR-22, UX-7): global, vendor or project. Switching on is one step with an impact preview and a reason. The gateway refuses requests in scope with KILL_SWITCH within 5 seconds. A red indicator stays in the header while one is on.
- Every one of these actions is written to an append-only, hash-chained audit record in the same transaction as the action. The viewer and the verify button arrive in phase 6.

**Out of scope.** SSO, SCIM, WebAuthn, self-service password change, e-mail, delegation and approval chains, time-boxed block overrides (SD-03 default is none), row-level security per tenant.

**Entry criteria.**

| Criterion | Status |
|---|---|
| Phase 4 exit criteria met and reviewed | Met. Owner go-ahead given 2026-11-20 ("go ahead for the full version"). Phases 5 and 6 are built in one run at the owner's request. |

**Risks.**

| Risk | Handling |
|---|---|
| A page or action is reachable without signing in | One middleware decides for every route from one table; a route missing from the table is refused. A test walks every route as an anonymous visitor and as each role. |
| One administrator lifts a block or a kill switch alone | The second approver is compared by user ID in the service, not in the template. Tests for self-approval on every kind. |
| An approval overrides a block | Approval only keeps the reserved budget for one resubmission. The resubmitted request passes the kill switch and block checks again. Test. |
| The demo needs an authenticator app | In demo mode the page shows the signed-in demo user's current code. It is refused in production together with all demo data. |
| An authenticator code is replayed | The last accepted time step is stored per user; the same or an older step is refused. Test. |
| A hard limit is left without an accountable person | Database trigger on budgets and on users. Disabling a user who owns a hard-limit budget is refused. |
| Signing in makes the database-down page unreachable | When the database cannot be reached nobody can be authenticated, so a 503 page is shown that still carries the DEMO label, Unknown health and the outage alert. |

## Exit criteria and result

| Exit criterion | Evidence | Result |
|---|---|---|
| Local accounts with TOTP; every page needs a session | `tests/system/test_access.py` (anonymous walk of every route; sign-in through the pages; session limits in `tests/integration/test_people_controls.py::test_session_timeouts`); RFC 6238 vectors in `tests/unit/test_identity_units.py` | Pass |
| Permission matrix on every route | `test_every_route_names_a_permission_and_no_entry_is_stale`, `test_a_route_without_a_permission_entry_is_refused`, `test_every_route_follows_the_permission_matrix` (4 roles), `test_permission_matrix_is_complete_and_least_privilege` | Pass |
| Step-up on policy changes | `test_admin_policy_change_requires_step_up`, `test_step_up_accepts_a_fresh_code_once` | Pass |
| HARD budgets cannot activate without an active owner | `test_hard_limit_without_owner_cannot_activate` (service and database trigger), `test_agent_cannot_be_owner`, `test_owner_of_a_hard_limit_cannot_be_disabled`, `test_hard_limit_needs_an_owner_through_the_pages` | Pass |
| HELD queue and approvals; approval shows the "one matching resubmission" copy | `test_held_queue_shows_metadata_impact_expiry_and_what_approving_does`, `test_approval_allows_one_matching_resubmission`, `test_unused_approval_expires_and_releases_the_budget`, `test_approval_does_not_override_a_block` | Pass |
| Requester cannot approve own request (brief: self-approval denied) | `test_self_approval_denied`, `test_held_request_eligibility`, `test_owner_of_the_requesting_project_cannot_approve`, `test_self_approval_is_disabled_with_a_reason_and_refused_if_forced`, `test_second_approver_must_differ` (database rule) | Pass |
| Lift requires a second administrator, with MFA, within 24 hours (brief) | `test_lift_block_requires_second_admin`, `test_two_person_request_expires_after_24_hours`, `test_block_lift_needs_a_second_administrator_through_the_pages`, `test_a_block_can_only_be_lifted_through_the_two_person_approval` | Pass |
| Kill switch denies within 5 s (brief); impact preview; two-person deactivation | `test_kill_switch_denies_within_5s`, `test_kill_switch_scopes`, `test_kill_switch_holds_while_the_ledger_is_down_and_for_approved_requests`, `test_kill_switch_off_requires_second_admin`, `test_kill_switch_preview_activation_indicator_and_two_person_off` | Pass |
| Every new field has help; every new failure path is visible | `tests/system/test_field_help.py` (163 registry entries, 43 calculated fields checked against code), `tests/system/test_failure_visibility.py` (18 codes, new: `ACCOUNT_LOCKED`) | Pass |
| Lint, secret scan and all tests pass | See the final test report, `docs/testing/test-report.md` | Pass |

Bypass route B-l (owner or override tampered to lift a limit) is now covered by the two-person rule and the audit chain.

**Checked by hand in Chromium against the Docker stack**, with two separate browser sessions (alice.admin and bob.admin): sign-in with the demo helper, approving a held request, the block lift, the kill switch on and off with the red header bar and the demo console, the owner rule on Call Notes, a third session as omar.owner for the role limits, and sign-out.

**Notes.**

- **Found by the tests and fixed.** (1) The kill switch preview counted zero recent requests for a project, because it compared the project's name with its display label. (2) Cancelling one's own request was grouped with the actions that need a fresh code. It now has its own permission. (3) A template variable named like an existing macro broke the Approvals page.
- **Found in the browser and fixed.** (1) Two sensitive actions within 30 seconds needed a page reload for the next demo code, which cleared the typed reason. The code now refreshes in place. (2) The held queue was wider than the page, so the Approve button was out of view. (3) The held queue now lists the newest request first, which is the one the demo console just sent.
- **Earlier tests whose expectation changed, with the reason.** Pages during a database outage now answer 503 with the outage page instead of 200 without data, because nobody can be authenticated (A-78). The cap on held requests is tested with different requests, because an identical request is now the same hold (A-80). The test that no code path lifts a block now checks that the only caller of the lift is the two-person approval. Forms that change policy send an authenticator code.
- Assumptions A-72 to A-86 and A-94 were recorded. A-79 (who counts as the requester of a held request), A-81 (no override) and A-82 (which other actions need two people) deserve the owner's review.

## Review record

| Date | Reviewer | Outcome |
|---|---|---|
| 2026-11-20 | Engineering self-review | Exit criteria met, with the notes above. |
| Pending | Product owner | Review of phases 5 and 6 together, as requested. |
