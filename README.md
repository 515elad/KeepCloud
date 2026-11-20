# KeepCloud

KeepCloud MVP (product name: KeepAir): visibility and enforceable budgets for AI spend.

**Status:** MVP complete, phase 6 of 6. Sign-in with password and authenticator code; a gateway that reserves budget before every request and refuses blocked vendors, blocked or unknown models, exhausted hard limits and anything under a kill switch, against a mock provider; fail-open through an encrypted spool for monitor and soft budgets; billing files allocated to projects with estimates, provider-reported and invoiced figures never mixed; owners, held-request approvals and two-person actions; a showback report with CSV export; a hash-chained audit log with a chain check. What the PRD asks for and the MVP does not have is listed in [docs/not-built.md](docs/not-built.md).

## Run it

Needs Docker. Nothing else: no account, no key, no internet service.

```bash
./run.sh
```

This builds and starts everything, loads the demo data and sends the scripted demo traffic. Then open <http://localhost:8000>.

| Command | What it does |
|---|---|
| `./run.sh` | Build, start, wait until ready, send the demo traffic |
| `KEEPAIR_UI_PORT=8100 ./run.sh` | The same on another port, if 8000 is taken. The choice is remembered. |
| `./run.sh traffic` | Send the 500 demo requests again |
| `./run.sh reset` | Reload the original demo data |
| `./run.sh stop` | Stop everything and delete the demo database |
| `./run.sh test` | Install the developer tools and run lint, secret scan and all tests (also needs [uv](https://docs.astral.sh/uv/)) |
| `./run.sh help` | List all commands and options |

On Windows, run it from WSL or Git Bash.

## Documents

- Demo scripts and all documents: [docs/README.md](docs/README.md)
- Requirements: [`claude/`](claude/)

Development happens on the `dev` branch. `main` holds reviewed releases only.
