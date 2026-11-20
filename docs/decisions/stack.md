# Stack decisions

The stack follows PRD v1.4 Section 2.3: Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 Core, Alembic, PostgreSQL 16, pytest, hypothesis, respx, testcontainers.

## UI: server-rendered (Jinja2 templates served by FastAPI)

The UI is server-rendered HTML with one small stylesheet and one small script, and no build step. The MVP screens are tables, forms and status displays, which plain HTML handles well and which are accessible by default (real headings, tables, buttons and links). One process serves both the API and the UI, so the demo starts with a single command and the offline tests can check every page by reading its HTML, including the rule that every field has an "i" entry. It also allows a strict Content-Security-Policy with no inline script or style (SEC-27). A React app would add a second toolchain, a second test stack and a client-side state layer without a matching benefit at this size. If a later screen needs rich client-side interaction (for example the cost explorer in phase 4), it can be added as a small script on that page without changing this decision.

## Other choices made in phase 0

| Choice | Reason |
|---|---|
| `psycopg` 3 driver | Current PostgreSQL driver for SQLAlchemy 2; binary wheels, no compiler needed. |
| Own counters with Prometheus text output (`keepair.metrics`) instead of a metrics library | No existing observability stack was found (V-3). A small in-process registry keeps each app instance and each test isolated. It can be replaced by OpenTelemetry (v1.4 Section 2.3) without changing callers. |
| `detect-secrets` as the secret scanner | Installs from the pinned lockfile, runs offline and identically on a laptop and in CI. |
| `uv` for lockfiles with hashes | Reproducible installs (SEC-43). |
| Native HTML `popover` for the "i" help | Works with a click even if the script fails to load; the script only adds focus-open and placement. |
| `python-multipart` (phase 4) | Needed to read a file upload from an HTML form. It is the parser the web framework itself expects. |
| `cryptography` (phase 3) | AES-256-GCM for the fail-open spool. A maintained, widely reviewed library; no cipher code of our own. |
