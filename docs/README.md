# KeepAir documentation

## Run the demo (about 5 minutes)

Needs Docker. No account, API key or internet service is used.

```bash
docker compose up --build
```

Open <http://localhost:8000>, then follow the demo script for the current phase.

| Phase | Demo script | Lifecycle record |
|---|---|---|
| 0 Foundation | [demo/phase-0.md](demo/phase-0.md) | [lifecycle/phase-0.md](lifecycle/phase-0.md) |

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
uv venv --python 3.12
uv pip sync --require-hashes requirements-dev.lock
uv pip install --no-deps -e .
.venv/bin/pytest --cov          # needs Docker for PostgreSQL 16
.venv/bin/ruff check . && .venv/bin/ruff format --check .
scripts/secret_scan.sh
```
