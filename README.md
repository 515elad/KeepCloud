# KeepCloud

KeepCloud MVP (product name: KeepAir): visibility and enforceable budgets for AI spend.

**Status:** phase 2 of 6. The gateway reserves budget before every request, refuses blocked vendors, blocked or unknown models and exhausted hard limits, and settles afterwards, against a mock provider. The UI shows budgets, the registry, the denials feed and live component health.

## Run it

Needs Docker. Nothing else: no account, no key, no internet service.

```bash
./run.sh
```

This builds and starts everything, loads the demo data and sends the scripted demo traffic. Then open <http://localhost:8000>.

| Command | What it does |
|---|---|
| `./run.sh` | Build, start, wait until ready, send the demo traffic |
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
