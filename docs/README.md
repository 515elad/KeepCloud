# KeepAir documentation

## Run the demo (about 5 minutes)

Needs Docker. No account, API key or internet service is used.

```bash
./run.sh
```

It builds and starts the stack, loads the demo data and sends the scripted demo traffic. Open <http://localhost:8000>, then follow the demo script for the current phase. The gateway listens on <http://localhost:8080>. `./run.sh help` lists the other commands (traffic, reset, stop, test).

The demo scripts name the underlying `docker compose` commands step by step; `./run.sh` runs the same ones.

| Phase | Demo script | Lifecycle record |
|---|---|---|
| 0 Foundation | [demo/phase-0.md](demo/phase-0.md) | [lifecycle/phase-0.md](lifecycle/phase-0.md) |
| 1 Budgets and policy visibility | [demo/phase-1.md](demo/phase-1.md) | [lifecycle/phase-1.md](lifecycle/phase-1.md) |
| 2 Gateway, ledger and denials | [demo/phase-2.md](demo/phase-2.md) | [lifecycle/phase-2.md](lifecycle/phase-2.md) |

## Map

| Folder | Contents |
|---|---|
| `../claude/` | Requirements: PRD v1.4 build spec and v1.5 combined addendum |
| `decisions/` | [Stack choices](decisions/stack.md), [assumptions log](decisions/assumptions.md) |
| `architecture/` | [Verification record](architecture/verification.md) (V-1 to V-8) |
| `testing/` | [Test plan](testing/test-plan.md) |
| `compliance/` | [ISO/IEC 25010](compliance/iso25010.md), [ISO/IEC 27001 Annex A](compliance/iso27001-annex-a.md). Alignment only; no certification is claimed. |
| `lifecycle/` | Plan, entry and exit criteria and review record per phase |
| `demo/` | Click-through demo scripts |

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
