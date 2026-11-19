#!/usr/bin/env sh
# Fails if any tracked file contains a secret that is not in the reviewed baseline.
set -eu
cd "$(dirname "$0")/.."
PATH="$PWD/.venv/bin:$PATH"
git ls-files -z -- . ':!requirements*.lock' ':!.secrets.baseline' \
  | xargs -0 detect-secrets-hook --baseline .secrets.baseline
echo "Secret scan passed."
