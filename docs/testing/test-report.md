# Final test report

State of the `dev` branch at the end of phase 6. Produced by `.venv/bin/pytest --cov` on 2026-11-20 against a throwaway PostgreSQL 16 container. No test calls a real provider or needs a key.

## Result

| | |
|---|---|
| Tests | **603** |
| Passed | **603** |
| Failed, errored, skipped, expected to fail | 0 |
| Pass rate | **100%** |
| Line and branch coverage, all modules | **95%** (5376 statements, 210 not run) |
| Lint (`ruff check`, `ruff format --check`) | Clean |
| Secret scan (`scripts/secret_scan.sh`) | Passed |

No test is skipped or marked as an expected failure. Every test names the PRD requirement it covers (`@pytest.mark.req`); a test without one stops the run.

| Level | Folder | Tests |
|---|---|---|
| Unit | `tests/unit` | 174 |
| Integration (real PostgreSQL) | `tests/integration` | 171 |
| System (the UI and the gateway through HTTP) | `tests/system` | 258 |

## Tests the brief asked for by name

| Phase | Asked for | Test |
|---|---|---|
| 1 | `effective_remaining` property test | `tests/unit/test_budgets.py` |
| 1 | Vendor-over-model precedence over all status combinations | `tests/unit/test_registry.py` |
| 1 | Cascade rendering | `tests/system/test_gateway_registry.py::test_cascade_rendering_for_models_of_a_blocked_vendor` |
| 2 | 200 concurrent reservations never exceed the cap | `tests/integration/test_ledger.py` |
| 2 | Idempotency; timeout after dispatch; bypass routes | `tests/integration/test_gateway_path.py`, `tests/integration/test_gateway_bypass.py` |
| 3 | Ledger down, spool full (must deny), replay idempotency | `tests/integration/test_fail_open.py` |
| 4 | Allocation shares sum to 100%; reingest is idempotent; estimates never labelled INVOICED | `tests/unit/test_billing_units.py`, `tests/integration/test_billing_ingest.py` |
| 5 | Self-approval denied | `test_self_approval_denied`, `test_second_approver_must_differ`, `test_owner_of_the_requesting_project_cannot_approve` |
| 5 | Lift requires a second administrator | `test_lift_block_requires_second_admin` |
| 5 | Kill switch denies within 5 s | `test_kill_switch_denies_within_5s` |
| 6 | Hash chain detects tampering | `tests/integration/test_audit_chain.py::test_audit_hash_chain_detects_tampering` and five more cases |
| 6 | App role cannot UPDATE or DELETE audit rows | `test_app_role_cannot_update_or_delete_audit_rows` |
| All | Every failure path: metric, alert record, UI row | `tests/system/test_failure_visibility.py` (18 codes) |
| All | Every field has help; formulas match the code | `tests/system/test_field_help.py` (163 entries, 43 formulas) |

## Coverage by package

| Package | Statements | Not run | Line coverage |
|---|---|---|---|
| `src/keepair (top level)` | 1557 | 37 | 97% |
| `src/keepair/billing` | 437 | 6 | 98% |
| `src/keepair/demo` | 370 | 40 | 89% |
| `src/keepair/gateway` | 1232 | 56 | 95% |
| `src/keepair/mockprovider` | 33 | 19 | 42% |
| `src/keepair/web` | 1747 | 52 | 97% |

## Coverage per module

The percentage combines lines and branches, as the coverage tool reports it.

| Module | Statements | Not run | Coverage |
|---|---|---|---|
| `src/keepair/__init__.py` | 1 | 0 | 100% |
| `src/keepair/approvals.py` | 147 | 6 | 95% |
| `src/keepair/audit.py` | 54 | 0 | 100% |
| `src/keepair/billing/__init__.py` | 0 | 0 | 100% |
| `src/keepair/billing/allocation.py` | 89 | 1 | 98% |
| `src/keepair/billing/finalization.py` | 34 | 1 | 95% |
| `src/keepair/billing/focus.py` | 176 | 4 | 97% |
| `src/keepair/billing/ingest.py` | 85 | 0 | 100% |
| `src/keepair/billing/reconcile.py` | 53 | 0 | 100% |
| `src/keepair/budgets.py` | 101 | 0 | 100% |
| `src/keepair/clock.py` | 26 | 0 | 100% |
| `src/keepair/config.py` | 21 | 0 | 100% |
| `src/keepair/coverage.py` | 15 | 0 | 100% |
| `src/keepair/db.py` | 7 | 2 | 71% |
| `src/keepair/demo/__init__.py` | 0 | 0 | 100% |
| `src/keepair/demo/billing.py` | 84 | 10 | 87% |
| `src/keepair/demo/seed.py` | 114 | 7 | 94% |
| `src/keepair/demo/tamper.py` | 24 | 8 | 60% |
| `src/keepair/demo/traffic.py` | 78 | 15 | 81% |
| `src/keepair/demo/tree.py` | 21 | 0 | 100% |
| `src/keepair/demo/usage_plan.py` | 49 | 0 | 98% |
| `src/keepair/exports.py` | 35 | 1 | 96% |
| `src/keepair/failures.py` | 104 | 8 | 91% |
| `src/keepair/formulas.py` | 218 | 0 | 99% |
| `src/keepair/gateway/__init__.py` | 0 | 0 | 100% |
| `src/keepair/gateway/adapters.py` | 57 | 2 | 96% |
| `src/keepair/gateway/app.py` | 102 | 7 | 92% |
| `src/keepair/gateway/auth.py` | 60 | 2 | 94% |
| `src/keepair/gateway/errors.py` | 18 | 0 | 100% |
| `src/keepair/gateway/estimate.py` | 25 | 0 | 100% |
| `src/keepair/gateway/fx.py` | 19 | 4 | 71% |
| `src/keepair/gateway/idempotency.py` | 39 | 2 | 96% |
| `src/keepair/gateway/ledger.py` | 111 | 1 | 98% |
| `src/keepair/gateway/ledgerstate.py` | 38 | 0 | 100% |
| `src/keepair/gateway/main.py` | 2 | 2 | 0% |
| `src/keepair/gateway/maintenance.py` | 103 | 10 | 89% |
| `src/keepair/gateway/parse.py` | 54 | 0 | 100% |
| `src/keepair/gateway/replay.py` | 41 | 0 | 100% |
| `src/keepair/gateway/service.py` | 285 | 23 | 91% |
| `src/keepair/gateway/snapshot.py` | 67 | 1 | 97% |
| `src/keepair/gateway/spool.py` | 184 | 2 | 98% |
| `src/keepair/gateway/tokens.py` | 27 | 0 | 100% |
| `src/keepair/health.py` | 51 | 0 | 100% |
| `src/keepair/help_registry.py` | 60 | 2 | 95% |
| `src/keepair/iam.py` | 215 | 7 | 95% |
| `src/keepair/ids.py` | 10 | 0 | 100% |
| `src/keepair/killswitch.py` | 87 | 1 | 98% |
| `src/keepair/metrics.py` | 33 | 0 | 97% |
| `src/keepair/mockprovider/__init__.py` | 0 | 0 | 100% |
| `src/keepair/mockprovider/app.py` | 31 | 17 | 42% |
| `src/keepair/mockprovider/main.py` | 2 | 2 | 0% |
| `src/keepair/money.py` | 22 | 0 | 100% |
| `src/keepair/owners.py` | 61 | 5 | 87% |
| `src/keepair/passwords.py` | 41 | 0 | 100% |
| `src/keepair/permissions.py` | 36 | 0 | 100% |
| `src/keepair/registry.py` | 123 | 5 | 94% |
| `src/keepair/rng.py` | 8 | 0 | 100% |
| `src/keepair/schema.py` | 37 | 0 | 100% |
| `src/keepair/startup.py` | 12 | 0 | 100% |
| `src/keepair/totp.py` | 32 | 0 | 100% |
| `src/keepair/web/__init__.py` | 0 | 0 | 100% |
| `src/keepair/web/access.py` | 4 | 0 | 100% |
| `src/keepair/web/app.py` | 489 | 19 | 93% |
| `src/keepair/web/auth_routes.py` | 102 | 0 | 100% |
| `src/keepair/web/control_routes.py` | 246 | 20 | 90% |
| `src/keepair/web/control_views.py` | 155 | 3 | 96% |
| `src/keepair/web/formatting.py` | 23 | 1 | 92% |
| `src/keepair/web/helpui.py` | 20 | 0 | 100% |
| `src/keepair/web/main.py` | 2 | 2 | 0% |
| `src/keepair/web/pages.py` | 18 | 0 | 100% |
| `src/keepair/web/record_routes.py` | 61 | 5 | 87% |
| `src/keepair/web/record_views.py` | 93 | 0 | 100% |
| `src/keepair/web/spend_views.py` | 216 | 1 | 99% |
| `src/keepair/web/views.py` | 318 | 1 | 99% |

## What the lowest figures mean

- `src/keepair/gateway/main.py` (0%).
- `src/keepair/mockprovider/main.py` (0%).
- `src/keepair/web/main.py` (0%).
- `src/keepair/mockprovider/app.py` (42%).
- `src/keepair/demo/tamper.py` (60%).
- `src/keepair/db.py` (71%).
- `src/keepair/gateway/fx.py` (71%).
- `src/keepair/demo/traffic.py` (81%).

The entry points (`main.py` files, the `__main__` blocks of the seed, traffic and tamper scripts) start a server or a script and are exercised by the Docker stack and the browser checks, not by the unit of code coverage. Error branches that need a database failure at one exact statement are covered where a failure injector exists and are otherwise left to the fail-closed default.

## Checks that are not automated

Each phase was walked in Chromium against the Docker stack; the lifecycle record of each phase lists what was clicked. These walks found defects that the HTTP-level tests could not (for example a form refused by a browser's Origin header in phase 1, and a table wider than the page in phase 5). They are not part of CI.

## How to repeat

```bash
./run.sh test
```
