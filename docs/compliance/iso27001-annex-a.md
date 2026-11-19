# ISO/IEC 27001:2022 Annex A mapping (MVP controls)

KeepAir is built to be **aligned with** these controls. This is not a certification, no certification is claimed, and the mapping has not been reviewed by an auditor (PRD v1.5 Section 13).

Status after phase 0. "Planned" means no code exists yet.

| Control | Topic | Status | Code | Test |
|---|---|---|---|---|
| A.5.15 | Access control | Planned, phase 5 (roles, route separation, SEC-14) | None | None |
| A.5.17 | Authentication information | Planned: gateway tokens stored as SHA-256 hash only (phase 2); TOTP MFA (phase 5) | None | None |
| A.5.18 | Access rights | Planned, phase 5 (owners, two-person actions) | None | None |
| A.8.15 | Logging | Partly: every failure writes an alert record. Tamper-evident audit log is phase 6. | `src/keepair/failures.py`, `src/keepair/schema.py` (`alerts`) | `tests/system/test_failure_visibility.py` |
| A.8.16 | Monitoring | Partly: failure counters at `/metrics`; heartbeat-based health with Unknown as a distinct state. Live heartbeats from phase 2. | `src/keepair/metrics.py`, `src/keepair/health.py` | `tests/unit/test_health_status.py`, `tests/unit/test_metrics.py`, `tests/integration/test_database.py::test_heartbeat_moves_a_component_from_unknown_through_every_state` |
| A.8.28 | Secure coding | In place for what exists: autoescaped templates, Content-Security-Policy without inline script or style, no float for money, no wall clock or unseeded randomness outside injected modules, lint with security rules (ruff `S`). | `src/keepair/web/app.py` (`SECURITY_HEADERS`), `src/keepair/money.py`, `pyproject.toml` | `tests/system/test_shell.py::test_security_headers_on_every_response`, `::test_pages_have_no_inline_script_or_style`, `tests/unit/test_no_wallclock.py`, `tests/unit/test_money.py` |
| A.8.29 | Security testing | Partly: secret scanner in CI with a self-test that plants a key. Bypass suite from phase 2. | `scripts/secret_scan.sh`, `.github/workflows/ci.yml` | `tests/unit/test_secret_scanner.py` |
| A.8.31 | Separation of environments | Partly: all configuration through environment variables; demo data labelled DEMO on every page; tests use a throwaway database. Refusing test material in production (SEC-23) is planned. | `src/keepair/config.py`, `ui/templates/base.html` | `tests/system/test_shell.py::test_demo_label_is_in_the_header_of_every_page` |
| A.8.32 | Change management | Partly: versioned migrations tested up and down; work on `dev` only, no force-push; CI on every push; dependencies pinned with hashes; CI actions pinned to commit SHAs. Branch protection on `main` is a repository setting for the owner. | `migrations/`, `requirements*.lock`, `.github/workflows/ci.yml` | `tests/integration/test_database.py::test_migration_downgrade_and_upgrade_round_trip` |
