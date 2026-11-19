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
