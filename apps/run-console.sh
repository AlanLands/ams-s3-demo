#!/usr/bin/env bash
# App 1 of 4 — the AMS Console (what the presenter drives).
#
# Two processes, one script: the FastAPI backend on :8000 and the Vite dev
# server on :5173. Open :5173 in the browser; it proxies API calls to :8000.
#
# Ctrl-C stops both.
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate

# Repo root on PYTHONPATH so `apps.console.api` and `apps.policycore` import
# without installing the project.
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"

if [ ! -d apps/console/web/node_modules ]; then
  echo "Installing console web dependencies (first run only)…"
  (cd apps/console/web && npm install)
fi

trap 'kill 0' EXIT

# No --reload: the reloader restarts the process mid-beat when codegen writes
# to the working tree, which drops the in-flight demo state.
uvicorn apps.console.api.main:app --port "${API_PORT:-8000}" &
(cd apps/console/web && npm run dev) &

echo
echo "  Console API  -> http://localhost:${API_PORT:-8000}"
echo "  Console UI   -> http://localhost:5173     <- open this one"
echo "  Ctrl-C to stop both."
wait
