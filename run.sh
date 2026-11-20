#!/usr/bin/env bash
# KeepAir demo: one command to build, start and load everything.
#
#   ./run.sh            build, start, wait until ready, send the demo traffic
#   ./run.sh start      the same
#   ./run.sh traffic    send the 500 scripted demo requests again (as new requests)
#   ./run.sh reset      reload the original demo data
#   ./run.sh status     show the services
#   ./run.sh logs       follow the logs
#   ./run.sh stop       stop everything and delete the demo database
#   ./run.sh test       install the developer tools and run lint, secret scan and all tests
#
# Options for start:  --no-traffic   do not send the demo traffic
#                     --no-build     reuse images that are already built
#
# If port 8000 or 8080 is taken:  KEEPAIR_UI_PORT=8100 KEEPAIR_GATEWAY_PORT=8180 ./run.sh
# The choice is remembered in .env, so later commands need no prefix.
#
# Needs Docker with the compose plugin. Nothing else. No account, key or
# internet service is used: the "vendor" is a mock server in the same stack.
set -euo pipefail
cd "$(dirname "$0")"

# Local settings live in .env (not in git): the two ports and the spool key.
# A port given on the command line is remembered there, so it is needed only once:
#   KEEPAIR_UI_PORT=8100 ./run.sh
ENV_FILE=".env"

saved() {  # saved NAME -> value from .env, or nothing
  [ -f "$ENV_FILE" ] && sed -n "s/^$1=//p" "$ENV_FILE" | tail -n 1 || true
}

remember() {  # remember NAME VALUE
  touch "$ENV_FILE"
  grep -v "^$1=" "$ENV_FILE" > "$ENV_FILE.tmp" || true
  printf '%s=%s\n' "$1" "$2" >> "$ENV_FILE.tmp"
  mv "$ENV_FILE.tmp" "$ENV_FILE"
}

for name in KEEPAIR_UI_PORT KEEPAIR_GATEWAY_PORT; do
  if [ -n "${!name:-}" ]; then
    remember "$name" "${!name}"
  elif [ -n "$(saved "$name")" ]; then
    export "$name=$(saved "$name")"
  fi
done
export KEEPAIR_UI_PORT="${KEEPAIR_UI_PORT:-8000}"
export KEEPAIR_GATEWAY_PORT="${KEEPAIR_GATEWAY_PORT:-8080}"

ensure_spool_key() {
  # A key for the gateway's encrypted fail-open spool, made once on this machine.
  if [ -z "$(saved KEEPAIR_SPOOL_KEY)" ]; then
    local key
    key="$(openssl rand -base64 32 2>/dev/null || head -c 32 /dev/urandom | base64)"
    remember KEEPAIR_SPOOL_KEY "$key"
  fi
}
UI_URL="http://localhost:$KEEPAIR_UI_PORT"
GATEWAY_URL="http://localhost:$KEEPAIR_GATEWAY_PORT"

say() { printf '\n==> %s\n' "$*"; }
fail() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

need_docker() {
  command -v docker >/dev/null 2>&1 || fail "Docker is not installed. Install Docker Desktop (or Docker Engine) and run this again."
  docker compose version >/dev/null 2>&1 || fail "The Docker compose plugin is missing. Update Docker and run this again."
  docker info >/dev/null 2>&1 || fail "Docker is installed but not running. Start Docker and run this again."
}

port_busy() {
  # True when something that is not this stack already listens on the port.
  (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null
}

check_ports() {
  # If our own UI is already running, the ports are ours.
  if [ -n "$(docker compose ps --status running -q app 2>/dev/null)" ]; then return; fi
  local name port
  for name in KEEPAIR_UI_PORT KEEPAIR_GATEWAY_PORT; do
    port="${!name}"
    if port_busy "$port"; then
      fail "Port $port is already used by another program. Pick another one, for example:
       $name=$((port + 100)) ./run.sh
       (it is remembered, so you only need to do this once)"
    fi
  done
}

send_traffic() {
  say "Sending 500 scripted demo requests through the gateway (run $1)"
  docker compose run --rm --no-deps demo-traffic python -m keepair.demo.traffic --run "$1"
}

start() {
  local traffic=1 build="--build"
  for arg in "$@"; do
    case "$arg" in
      --no-traffic) traffic=0 ;;
      --no-build) build="--no-build" ;;
      *) fail "Unknown option for start: $arg" ;;
    esac
  done
  need_docker
  check_ports
  ensure_spool_key
  say "Building and starting KeepAir (database, UI, gateway, mock vendor)"
  docker compose up -d $build --wait
  if [ "$traffic" = 1 ]; then send_traffic 1; fi
  cat <<MSG

KeepAir is running.

  UI        $UI_URL            (start here)
  Gateway   $GATEWAY_URL/v1/chat/completions
  Demo script: docs/demo/phase-3.md

  ./run.sh traffic   send the demo traffic again
  ./run.sh reset     reload the original demo data
  ./run.sh stop      stop everything
MSG
}

case "${1:-start}" in
  start) shift || true; start "$@" ;;
  --no-traffic|--no-build) start "$@" ;;
  traffic) need_docker; send_traffic "$(date +%s)" ;;
  reset)
    need_docker
    say "Reloading the demo data"
    docker compose restart app
    docker compose up -d --no-build --wait app
    echo "Done. Budgets, registry and credentials are back to the seeded state."
    ;;
  status) need_docker; docker compose ps ;;
  logs) need_docker; docker compose logs -f ;;
  stop)
    need_docker
    say "Stopping KeepAir and deleting the demo database"
    docker compose --profile demo down -v --remove-orphans
    ;;
  test)
    command -v uv >/dev/null 2>&1 || fail "The 'uv' tool is needed for this. Install it from https://docs.astral.sh/uv/ and run this again."
    need_docker
    say "Installing the pinned developer tools into .venv"
    uv venv --python 3.12 --allow-existing -q
    uv pip sync -q --require-hashes requirements-dev.lock
    uv pip install -q --no-deps -e .
    say "Lint";        .venv/bin/ruff check . && .venv/bin/ruff format --check .
    say "Secret scan"; scripts/secret_scan.sh
    say "Tests (starts a throwaway PostgreSQL 16 container)"
    .venv/bin/pytest --cov
    ;;
  -h|--help|help) sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//' ;;
  *) fail "Unknown command: $1. Run ./run.sh help" ;;
esac
