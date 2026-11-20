# Phase 6: Reports, audit log and tamper evidence

Lifecycle record, aligned with ISO/IEC 12207 (plan, entry and exit criteria, review).

## Plan

**Scope.**

- Showback report by project for a calendar month, with one finalization state per column, and a CSV export (FR-12).
- CSV cells that start with `=`, `+`, `-`, `@` or the full-width at sign are neutralized (SEC-29). Every export is audited.
- Audit log viewer: every admin, policy, budget, owner, override and kill-switch action, with a hash chain (`prev_hash`, `row_hash`). The records are written since phase 5, in the transaction of the action.
- A verify button that recomputes the chain and shows the result. A failure is a SEV1 alert. The gateway's upkeep loop also verifies at start and daily (SEC-32).
- The running services connect with a database role that cannot UPDATE or DELETE audit rows. Triggers refuse those statements for every role.
- Demo: export a report, open the audit log, verify, tamper with one row from a script, and see the verify failure and the SEV1 alert.

**Out of scope.** Signed chain head anchored outside the database (SEC-32), scheduled reports and e-mail delivery, chargeback posting, period lock, audit of every gateway denial in the chain.

**Entry criteria.**

| Criterion | Status |
|---|---|
| Phase 5 exit criteria met | Met (see `phase-5.md`). Built in the same run at the owner's request. |

**Risks.**

| Risk | Handling |
|---|---|
| An action happens without its audit record | The record is appended in the same database transaction. If the chain head is missing the action fails. Test. |
| The application can rewrite its own audit log | Separate database role without UPDATE, DELETE or TRUNCATE on the table, and a trigger. Test under that role. |
| The restricted role breaks the services | An integration test runs the gateway and the UI under the role. The Docker stack runs under it and was walked in a browser. |
| A name or reason in the export runs as a spreadsheet formula | Neutralization of every text cell; amounts are the only exempt cells and are written from integers. Property test. |
| A report adds an estimate to an invoice | One state per column, totals per column only, a state chip on every total. |
| The chain check is believed to prove more than it does | The page, the help text and the demo script state what it cannot detect. |

## Exit criteria and result

| Exit criterion | Evidence | Result |
|---|---|---|
| Showback report and CSV export | `tests/system/test_reports_audit.py` (`test_showback_lists_every_project_with_one_state_per_column`, `test_csv_export_has_the_same_rows_with_exact_amounts`, `test_who_may_download`) | Pass |
| CSV cells starting with `=`, `+`, `-`, `@` are neutralized (brief) | `test_csv_formula_neutralized` (7 start characters), `test_no_text_cell_can_start_a_formula` (property), `test_csv_formula_neutralized_in_the_export` (5 cases through the real export) | Pass |
| Every admin, policy, budget, owner, override and kill-switch action is recorded | `test_every_post_route_has_an_audit_expectation` (guard: a new POST route needs an entry), `test_every_admin_action_audited` (21 routes), `test_an_action_and_its_audit_record_are_one_transaction` | Pass |
| Hash chain detects tampering (brief) | `tests/integration/test_audit_chain.py`: changed record, each covered field, removed record, removed tail, inserted record, rewritten hash | Pass |
| App role cannot UPDATE or DELETE audit rows (brief) | `test_app_role_cannot_update_or_delete_audit_rows` (7 statements), `test_trigger_refuses_changes_even_for_a_role_with_the_privilege`, `test_the_services_work_under_the_restricted_role` | Pass |
| Verify button shows the result; tampering shows as a SEV1 alert | `test_verify_button_recomputes_the_chain_and_shows_the_result`, `test_tampering_is_shown_as_a_verify_failure_and_a_sev1_alert`, `test_gateway_upkeep_verifies_the_chain_at_start_and_daily`, failure-visibility injector for `AUDIT_CHAIN_BROKEN` | Pass |
| Lint, secret scan and all tests pass | `docs/testing/test-report.md` | Pass |

**Checked by hand in Chromium against the Docker stack.** The CSV download through a real click, the audit log, verify (intact), `./run.sh tamper`, verify (broken at record 8), the SEV1 row on Overview, and the "i" popover on a new field.

**Notes.**

- Uncontrolled-spend, quarantine and the other failure codes are unchanged. Two codes were added in phases 5 and 6: `ACCOUNT_LOCKED` (SEV3) and `AUDIT_CHAIN_BROKEN` (SEV1).
- The demo stack now uses two database roles. An existing demo database is upgraded in place by the migrations at start.
- Assumptions A-87 to A-93 were recorded. A-87 (gateway denials are not in the chain) and A-89 (what the chain cannot detect) deserve the owner's review.

## Review record

| Date | Reviewer | Outcome |
|---|---|---|
| 2026-11-20 | Engineering self-review | Exit criteria met, with the notes above. |
| Pending | Product owner | Final review. |
