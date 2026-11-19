# Phase 1: Budgets and policy visibility

Lifecycle record, aligned with ISO/IEC 12207 (plan, entry and exit criteria, review).

## Plan

**Scope.**

- Organization, department, team and project hierarchy with one budget per scope (FR-04): cap, currency, period, mode (independent or subdivision), policy (monitor, soft, hard, approval).
- Effective remaining allowance, defined once as a pure function and used by the UI (and by the gateway from phase 2).
- Budget bar with committed, reserved and remaining stacked and ticks at 50, 80, 90 and 100% (UX-8). Subdivision warning next to effective remaining.
- Vendor and model registry with Allowed and Blocked status, aliases, and the pure block decision (FR-18). Vendor block overrides model allow. Unknown models are denied.
- Block cascade in the UI (UX-3): an inherited model shows "Blocked by vendor X" with a lock and a disabled switch.
- Adding a block from the UI, with a reason and an impact preview. Lifting a block stays disabled until the two-person flow exists (phase 5).
- Coverage badge on every project: Gateway-routed by default (UX-2, UX-D1), labelled pending decision.
- Unregistered models listed separately from blocked ones (UX-4, D-03).
- Demo data: 3 departments, 6 teams, 12 projects, 2 vendors (one blocked), one unregistered model, budgets in USD and EUR.

**Out of scope.** Gateway, reservations in the database, credentials, owners and sign-in, approvals, forecasts, creating or editing budgets from the UI, lifting a block, audit log.

**Entry criteria.**

| Criterion | Status |
|---|---|
| Phase 0 exit criteria met and reviewed | Met. Owner go-ahead given 2026-11-19. |
| Requirements read: FR-04, FR-17, FR-18, UX-2, UX-3, UX-4, UX-8, D-03, SD-03, UX-D1 | Met. |

**Risks.**

| Risk | Handling |
|---|---|
| A model shows Allowed under a blocked vendor | One function gives the displayed status; property test over every status combination; rendering test on the page. |
| The UI and the future gateway compute remaining allowance differently | One pure function (`keepair.budgets.effective_remaining`); the UI calls it; property tests. |
| Reserved money is read as spent | Stacked bar with a hatched reserved segment and a text summary (UX-8). |
| Blocking from the UI before sign-in exists | Adding a block only narrows access. Lifting is disabled. Cross-site form posts are refused. The app stays on localhost. |
| "Enforced" is claimed too early | Badge function returns Enforced only when egress is verified, which cannot happen in the MVP. |
| The PRD rule for independent and subdivision budgets is open to more than one reading | Reading recorded in `docs/decisions/assumptions.md` (A-16, A-17) and shown in the "i" text. |

## Exit criteria and result

| Exit criterion | Evidence | Result |
|---|---|---|
| Hierarchy and budgets visible with bar, ticks, remaining and effective remaining | `tests/system/test_budgets_pages.py` | Pass |
| `effective_remaining` property tests | `tests/unit/test_budgets.py` (`test_effective_remaining_is_the_minimum_over_the_enforcing_path`, `test_effective_remaining_never_negative_after_any_reserve_and_settle_sequence`, and the two tests named in PRD v1.4 FR-04) | Pass |
| Vendor-over-model precedence over all status combinations and every alias | `tests/unit/test_registry.py::test_blocked_vendor_denies_even_when_model_allowed` plus the other FR-18 named tests that apply (`test_unknown_alias_denies`, `test_alias_to_blocked_model_denies`, `test_blocked_vendor_not_bypassed_by_model_alias`) | Pass |
| Cascade rendering: lock, "Blocked by vendor X", disabled switch, never Allowed | `tests/system/test_gateway_registry.py` | Pass |
| Coverage badge on every project, Gateway-routed, never Enforced | `test_every_project_has_a_gateway_routed_badge_and_none_claims_enforced` | Pass |
| Every new field has a registry entry; worked examples match the code | `tests/system/test_field_help.py` (walks 32 pages; 8 calculated fields checked against code) | Pass |
| Demo data matches the brief and is deterministic | `tests/integration/test_demo_data.py`, `test_seed_twice_gives_identical_data` | Pass |
| Migration matches the declared schema, up and down | `test_migrated_database_matches_the_declared_schema`, `test_migration_downgrade_and_upgrade_round_trip` | Pass |
| Lint, secret scan and all tests pass | 205 tests, 0 failures; 98% line coverage | Pass locally and in CI (commit `a15d508`) |

**Notes.**

- During the phase, the guard test for wall-clock and randomness use failed on a new file that imported `random` for a type hint. The code was changed; the test was not.
- FR-18 tests that need the gateway, the snapshot cache or two administrators (`test_block_propagates_within_5s_across_instances`, `test_block_fails_closed_when_snapshot_stale`, `test_lift_block_requires_second_admin`, `test_self_confirmation_denied`) are due in phases 2 and 5.
- Assumptions A-16 to A-28 were recorded in `docs/decisions/assumptions.md`. A-16 and A-17 (how independent and subdivision budgets limit and count spend) deserve the owner's review, because the gateway will enforce exactly this rule from phase 2.

## Review record

| Date | Reviewer | Outcome |
|---|---|---|
| 2026-11-19 | Engineering self-review | Exit criteria met. |
| Pending | Product owner | Go-ahead needed before phase 2. |
