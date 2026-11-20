# KeepAir documentation

## Run the demo (under 10 minutes)

Needs Docker with the compose plugin. No account, API key or internet service is used.

1. Start everything:

   ```bash
   ./run.sh
   ```

   It builds and starts the stack (database, UI, gateway, mock vendor), loads the demo data and sends 500 scripted requests through the gateway. The first build takes a few minutes; later starts take seconds.

2. Open <http://localhost:8000>. Sign in as `alice.admin`. The sign-in page lists the demo accounts with their password, and the next page shows the authenticator code.

3. A ten-minute tour, each step with what you should see:
   - **Budgets and gateway** (2 min): [demo/phase-1.md](demo/phase-1.md) steps for the budget tree, then the Gateway page with denials by reason.
   - **Approvals, block lift, kill switch** (5 min): [demo/phase-5.md](demo/phase-5.md), steps 10 to 22. Needs a second browser window for `bob.admin`.
   - **Report, audit log, tamper check** (3 min): [demo/phase-6.md](demo/phase-6.md), steps 4 to 13.

4. Stop and delete the demo database:

   ```bash
   ./run.sh stop
   ```

The gateway listens on <http://localhost:8080>. `./run.sh help` lists the other commands (traffic, reset, tamper, stop, test). If a port is taken, `KEEPAIR_UI_PORT=8100 ./run.sh` picks another one and remembers it in `.env`.

Every page carries a DEMO label. Every field, column and figure has an "i" button that explains its meaning, unit, source, formula and a worked example on the demo data.

| Phase | Demo script | Lifecycle record |
|---|---|---|
| 0 Foundation | [demo/phase-0.md](demo/phase-0.md) | [lifecycle/phase-0.md](lifecycle/phase-0.md) |
| 1 Budgets and policy visibility | [demo/phase-1.md](demo/phase-1.md) | [lifecycle/phase-1.md](lifecycle/phase-1.md) |
| 2 Gateway, ledger and denials | [demo/phase-2.md](demo/phase-2.md) | [lifecycle/phase-2.md](lifecycle/phase-2.md) |
| 3 Fail-open spool and visibility of failures | [demo/phase-3.md](demo/phase-3.md) | [lifecycle/phase-3.md](lifecycle/phase-3.md) |
| 4 Spend data, allocation and reconciliation | [demo/phase-4.md](demo/phase-4.md) | [lifecycle/phase-4.md](lifecycle/phase-4.md) |
| 5 Owners, approvals and two-person actions | [demo/phase-5.md](demo/phase-5.md) | [lifecycle/phase-5.md](lifecycle/phase-5.md) |
| 6 Reports, audit log and tamper evidence | [demo/phase-6.md](demo/phase-6.md) | [lifecycle/phase-6.md](lifecycle/phase-6.md) |

The demo scripts of phases 0 to 4 were written before sign-in existed. Sign in first (step 2 above); where a form now asks for an authenticator code, type the one shown next to the input.

## Map

| Folder | Contents |
|---|---|
| `../claude/` | Requirements: PRD v1.4 build spec and v1.5 combined addendum |
| `decisions/` | [Stack choices](decisions/stack.md), [assumptions log](decisions/assumptions.md) |
| `architecture/` | [Verification record](architecture/verification.md) (V-1 to V-8) |
| `testing/` | [Test plan](testing/test-plan.md), [final test report](testing/test-report.md) |
| `not-built.md` | [PRD requirements not built in the MVP](not-built.md), each with the reason |
| `compliance/` | [ISO/IEC 25010](compliance/iso25010.md), [ISO/IEC 27001 Annex A](compliance/iso27001-annex-a.md). Alignment only; no certification is claimed. |
| `lifecycle/` | Plan, entry and exit criteria and review record per phase |
| `demo/` | Click-through demo scripts |
| `../demo/billing/` | Generated demo billing files to upload on the Spend page |

## Develop

```bash
./run.sh test
```

This installs the pinned tools into `.venv` and runs lint, the secret scan and all tests (needs Docker for PostgreSQL 16, and `uv`). The single steps:

```bash
uv venv --python 3.12
uv pip sync --require-hashes requirements-dev.lock
uv pip install --no-deps -e .
.venv/bin/pytest --cov
.venv/bin/ruff check . && .venv/bin/ruff format --check .
scripts/secret_scan.sh
```
