# Phase 0: Foundation

Lifecycle record, aligned with ISO/IEC 12207 (plan, entry and exit criteria, review).

## Plan

**Scope.** Repository structure; docker compose (app and PostgreSQL 16); CI with offline tests, linting and a secret scanner; UI shell with eight pages; health strip (UX-6); the "i" information system on every field shown; a seeded demo data set; injected clock and randomness; failure visibility. No business logic.

**Out of scope.** Budgets, registry, gateway, sign-in, audit log. Each page says which phase delivers them.

**Entry criteria.**

| Criterion | Status |
|---|---|
| Both PRD documents read (v1.4 build spec, v1.5 addendum) | Met. Copies are in `claude/`. |
| Repository reachable; `main` has a README; work happens on `dev` | Met. |
| Verification gates recorded | Met with limits: see `docs/architecture/verification.md`. V-1 is not verified. |

**Risks.**

| Risk | Handling |
|---|---|
| A page ships a field with no help entry | Rendering a field with an unknown ID raises; a test walks every page. |
| Help text drifts from the code | Worked examples are recomputed from the code on demo data in a test. |
| Unknown health reads as healthy | Unknown has its own neutral style, icon and word; a test checks it never uses the healthy colour. |
| A failure is swallowed | Every registered failure code must have a test proving metric, alert and UI row. |
| Wall-clock or random calls creep in | A test scans the source for them outside `clock.py` and `rng.py`. |
| No sign-in yet | The app is published on localhost only. Recorded as A-11. |

## Exit criteria and result

| Exit criterion | Evidence | Result |
|---|---|---|
| Shell runs with eight pages, each naming phase and PRD requirement | `tests/system/test_shell.py` | Pass |
| Health strip shows every component as Unknown, never green | `tests/system/test_shell.py` | Pass |
| "i" popover works and every field has a registry entry | `tests/system/test_field_help.py`; browser check (click, keyboard focus, Escape) | Pass |
| Worked examples match the code on demo data | `test_worked_example_matches_the_code_on_demo_data` | Pass |
| Demo data is deterministic and labelled DEMO on every page | `test_seed_twice_gives_identical_data`; `test_demo_label_is_in_the_header_of_every_page` | Pass |
| Every failure path leaves a metric, an alert and a UI row | `tests/system/test_failure_visibility.py` | Pass |
| Lint and secret scan clean | `ruff check`, `scripts/secret_scan.sh` | Pass |
| Stack starts with docker compose | Built and started; pages load; app runs as non-root | Pass (see note) |
| Tests pass offline | 131 tests, 0 failures | Pass |

**Note on the image build.** In the build sandbox, the image was built with the sandbox's proxy certificate added, because outbound TLS there goes through an inspecting proxy. The committed `Dockerfile` has not been built on an ordinary network yet. The CI workflow (lint, secret scan, tests) passed on GitHub for commit `14b8426`.

## Review record

| Date | Reviewer | Outcome |
|---|---|---|
| 2026-11-19 | Engineering self-review | Exit criteria met, with the two notes above. |
| Pending | Product owner | Go-ahead needed before phase 1. |
