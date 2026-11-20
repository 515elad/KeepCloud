# KeepCloud

KeepCloud MVP (product name: KeepAir): visibility and enforceable budgets for AI spend.

**Status:** phase 4 of 6. The gateway reserves budget before every request and refuses blocked vendors, blocked or unknown models and exhausted hard limits, against a mock provider; monitor and soft budgets continue through an encrypted spool when the ledger is down. Billing files can be loaded and are allocated to projects; estimates, provider-reported and invoiced figures are shown side by side and never mixed; usage the gateway did not see is flagged.

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
