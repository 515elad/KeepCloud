# Test plan

Aligned with ISO/IEC 29119 (test levels, traceability). This is alignment, not certification.

## Principles (PRD v1.4 Section 2.7)

- Deterministic, mocked, offline. No test calls a real provider or needs a credential.
- Time and randomness are injected (`keepair.clock`, `keepair.rng`).
- The only external process is a local PostgreSQL 16 container started by testcontainers. Set `KEEPAIR_TEST_DATABASE_URL` to use an existing database instead.
- A control is never weakened to make a test pass.

## Levels

| Level | Folder | Scope | Needs database |
|---|---|---|---|
| Unit | `tests/unit/` | Pure functions and single modules: money, clock, health status, help registry schema, metrics, source scans | No |
| Integration | `tests/integration/` | Code against real PostgreSQL: migrations, seed, heartbeats | Yes |
| System | `tests/system/` | The running app through HTTP: pages, "i" system, failure visibility, security headers | Yes |

Later phases add property tests (hypothesis), concurrency tests, adapter contract tests (respx with fixtures in `tests/fixtures/providers/`), the bypass suite and fault injection, as listed in PRD v1.4 Section 2.7.

## Traceability

Every test carries `@pytest.mark.req(...)` naming the PRD requirement, security control or brief rule it covers. Collection fails if a test has none (`tests/conftest.py`). List the mapping with:

```bash
.venv/bin/pytest --collect-only -q -m req
```

Phase 0 coverage:

| Requirement | Tests |
|---|---|
| UX-1 navigation and page roadmap | `test_shell.py::test_every_page_opens_with_full_navigation`, `test_unbuilt_sections_say_which_phase_and_requirement` |
| UX-6 health strip, Unknown never green | `test_health_strip_shows_every_component_as_unknown`, `test_unknown_status_style_never_uses_the_healthy_colour`, `test_health_status.py` |
| FR-21 / SEC-37 heartbeats | `test_heartbeat_moves_a_component_from_unknown_through_every_state` |
| SEC-36 / hard rule 5 failure visibility | `test_failure_visibility.py` (one case per registered failure code) |
| Information system ("i") | `test_field_help.py`, `test_help_registry.py` |
| Hard rule 2 demo data | `test_seed_twice_gives_identical_data`, `test_demo_label_is_in_the_header_of_every_page` |
| FR-02 money as micro-units, ISO 4217 | `test_money.py`, `test_money_column_is_bigint_and_currency_is_checked` |
| ISO 8601, UTC storage | `test_clock_rng.py`, `test_timestamps_are_stored_with_timezone` |
| Injected clock and randomness | `test_no_wallclock.py` |
| SEC-27 output encoding and CSP | `test_security_headers_on_every_response`, `test_pages_have_no_inline_script_or_style` |
| SEC-44 secret scanning | `test_secret_scanner.py` |
| UX-14 accessibility basics | `test_accessibility_basics` |

Phase 1 coverage:

| Requirement | Tests |
|---|---|
| FR-04 effective remaining | `tests/unit/test_budgets.py`: `test_hierarchy_ancestor_cap_enforced_when_child_has_room`, `test_independent_child_ignores_parent_remaining_for_own_cap`, two property tests |
| FR-18 / SEC-05 block precedence, default deny | `tests/unit/test_registry.py`: `test_blocked_vendor_denies_even_when_model_allowed` (property, all status combinations and aliases), `test_unknown_alias_denies`, `test_alias_to_blocked_model_denies`, `test_blocked_vendor_not_bypassed_by_model_alias` |
| FR-18 emergency block, reason, no lift path | `tests/integration/test_demo_data.py`, `tests/system/test_gateway_registry.py` |
| UX-3 block cascade | `test_cascade_rendering_for_models_of_a_blocked_vendor`, `test_no_model_ever_renders_allowed_under_a_blocked_vendor` |
| UX-4 unregistered label | `test_unregistered_is_a_separate_label_with_its_own_action` |
| UX-2 / UX-D1 coverage badge | `test_every_project_has_a_gateway_routed_badge_and_none_claims_enforced`, `test_enforced_is_claimed_only_with_custody_and_verified_egress` |
| UX-8 budget bar and subdivision warning | `tests/system/test_budgets_pages.py` |
| TB-9 cross-site form posts | `test_cross_site_form_post_is_refused` |
| SEC-27 output encoding | `test_reason_text_is_escaped_when_shown` |

Property tests use hypothesis. The budget property test builds random budget trees and random sequences of reserve and settle, and checks that no limiting budget ever goes below zero.

Phase 2 coverage (the full bypass table is in `docs/lifecycle/phase-2.md`):

| Requirement | Tests |
|---|---|
| FR-05 request path, attribution | `tests/integration/test_gateway_path.py` |
| FR-05 concurrency, settle once, expiry, no partial state | `tests/integration/test_ledger.py` |
| SEC-01 no dispatch without a reservation; bypass suite | `tests/integration/test_gateway_bypass.py` |
| SEC-04 strict parsing, SEC-11 denial contract, SEC-12/22 tokens, estimator bound | `tests/unit/test_gateway_units.py` (includes property tests and parser fuzzing) |
| SEC-34 / hard rule 8: no token, key or prompt in logs or any table | `test_logs_contain_no_prompt_or_key_material` |
| FR-21 heartbeats, demo traffic determinism, latency evidence | `tests/integration/test_gateway_operations.py` |
| UX-5 denials feed, credentials, live health strip | `tests/system/test_gateway_activity.py` |

Provider calls are mocked with respx. The mocked answer uses the same fixture template and the same usage rule as the mock provider server, so tests and the demo stack behave alike. Fixtures are in `tests/fixtures/providers/`.

The concurrency test uses 200 threads against a real PostgreSQL 16 container. Fault injection replaces one function with one that raises (database error, provider timeout, stale snapshot).

Phase 3 coverage:

| Requirement | Tests |
|---|---|
| SEC-06 fail-open through the spool, fail closed for hard limits and blocks | `tests/integration/test_fail_open.py` |
| Spool: encryption, caps, restart, tampering, key rules | `tests/integration/test_fail_open.py` (spool section) |
| UX-7 banner and acknowledgement, FR-12 fail-open report, demo console | `tests/system/test_fail_open_ui.py` |

Fault injection in phase 3: a switch that makes ledger writes fail, an engine that points at a closed port (PostgreSQL gone), a disk that refuses to flush, a process that dies after dispatch, and a spool file with changed or foreign lines.

Phase 4 coverage:

| Requirement | Tests |
|---|---|
| FR-07 finalization states, FR-03 allocation, FR-06 join confidence, SEC-28 file parser | `tests/unit/test_billing_units.py` (property tests for exact splits and full accounting; fuzz tests for the parser) |
| FR-01 idempotent ingestion and revisions, FR-19 uncontrolled spend | `tests/integration/test_billing_ingest.py` |
| Spend and Reconciliation pages, upload, quarantine, manual assignment, coverage badge | `tests/system/test_spend_pages.py` |

Billing fixtures are the generated demo files in `demo/billing/`. `test_committed_demo_billing_files_are_what_the_generator_writes` keeps the committed copies equal to the generator's output.

Phase 5 and 6 coverage:

| Requirement | Tests |
|---|---|
| FR-13 TOTP, passwords, permission matrix; SEC-15 rules; FR-22 scope rule; SEC-29 neutralization; SEC-32 hash | `tests/unit/test_identity_units.py` (RFC 6238 vectors, a property test for CSV cells) |
| FR-13 sign-in, sessions, lockout, step-up; FR-17 owner rule; FR-11 held requests; SEC-07 and SEC-15 two-person actions; FR-22 kill switch | `tests/integration/test_people_controls.py` |
| SEC-32 tamper evidence, the restricted database role, the daily verifier | `tests/integration/test_audit_chain.py` |
| FR-13 and SEC-14: every route as an anonymous visitor and as each role; step-up on every policy route | `tests/system/test_access.py` |
| UX-7, UX-11, UX-D2 pages: approvals, block lift, kill switch, owners, users | `tests/system/test_people_pages.py` |
| FR-12 showback and export; SEC-31 every administrative action audited; verify and tamper | `tests/system/test_reports_audit.py` |

Guard tests that fail when something new is added without its test: a route without a permission entry (`test_every_route_names_a_permission_and_no_entry_is_stale`), a POST route without an audit expectation (`test_every_post_route_has_an_audit_expectation`), a failure code without an injector, a field without help.

## Browser checks

HTTP-level tests do not send everything a browser sends. After a phase 1 defect that only a real browser showed (see `docs/lifecycle/phase-2.md`), every form is also clicked through in Chromium before a phase is closed: block, create credential, revoke, the demo console buttons, Acknowledge, the billing file upload and the manual assignment, sign-in with two separate sessions, approvals, the block lift, the kill switch, the CSV download and the audit chain check before and after `./run.sh tamper`. This is manual for now; an automated browser test is a candidate for the next phase.

## How to run

```bash
uv venv --python 3.12 && uv pip sync --require-hashes requirements-dev.lock && uv pip install --no-deps -e .
.venv/bin/pytest --cov
.venv/bin/ruff check . && .venv/bin/ruff format --check .
scripts/secret_scan.sh
```

## Not automated in phase 0

- Browser behaviour of the "i" popover (click, keyboard focus, Escape, placement) and colour contrast were checked by hand in Chromium, light and dark. An automated browser test and an automated contrast check are candidates for a later phase.
- Performance: there is no gateway yet, so the p95 target in PRD v1.4 Section 2.4 has nothing to measure.
