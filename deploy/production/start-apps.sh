#!/usr/bin/env bash
# Starts all four backend processes detached, one PID file each under logs/.
# Unlike apps/run-console.sh (foreground, traps `kill 0`), this survives the
# shell that launched it — nginx fronts the ports, and stop-apps.sh is how you
# bring it down. The React UI is not started here: it is built once and served
# by nginx from apps/console/web/dist.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

if [ -z "${VIRTUAL_ENV:-}" ] && [ -f .venv/bin/activate ]; then
  source .venv/bin/activate
fi

export PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"

# Sourced through a CRLF-stripped copy: a .env edited on Windows leaves \r on
# every value, and a trailing \r inside a port or URL fails in ways that read
# like a network problem rather than a parsing one.
if [ -f .env ]; then
  tmp_env="$(mktemp)"
  sed 's/\r$//' .env > "$tmp_env"
  set -a
  . "$tmp_env"
  set +a
  rm -f "$tmp_env"
fi

API_PORT="${API_PORT:-20111}"
STREAMLIT_PORT="${STREAMLIT_PORT:-20112}"
POLICY_SERVICE_PORT="${POLICY_SERVICE_PORT:-20113}"
CLAIMS_SERVICE_PORT="${CLAIMS_SERVICE_PORT:-20114}"
BASE_URL_PATH="${STREAMLIT_BASE_URL_PATH:-sl_policycore}"
BIND_HOST="${BIND_HOST:-127.0.0.1}"
# Claims-Service dials this for policy lookups; default it to whatever port
# Policy-Service actually got above rather than a second hard-coded number.
export POLICY_SERVICE_URL="${POLICY_SERVICE_URL:-http://127.0.0.1:${POLICY_SERVICE_PORT}}"

mkdir -p logs

start() {
  local name="$1"; shift
  if [ -f "logs/$name.pid" ] && kill -0 "$(cat "logs/$name.pid")" 2>/dev/null; then
    echo "  $name already running (pid $(cat "logs/$name.pid")) — skipping"
    return
  fi
  nohup "$@" >> "logs/$name.log" 2>&1 &
  echo $! > "logs/$name.pid"
  echo "  $name -> pid $! (logs/$name.log)"
}

start console-api python -m uvicorn apps.console.api.main:app \
    --host "$BIND_HOST" --port "$API_PORT"

start policycore python -m streamlit run apps/policycore/app.py \
    --server.port "$STREAMLIT_PORT" \
    --server.address "$BIND_HOST" \
    --server.baseUrlPath "$BASE_URL_PATH" \
    --server.headless true \
    --browser.gatherUsageStats false

start policy-service python -m uvicorn apps.claimsportal.policy_service.main:app \
    --host "$BIND_HOST" --port "$POLICY_SERVICE_PORT"

start claims-service python -m uvicorn apps.claimsportal.claims_service.main:app \
    --host "$BIND_HOST" --port "$CLAIMS_SERVICE_PORT"

echo
echo "  Console API    -> http://${BIND_HOST}:${API_PORT}                    (nginx /api/)"
echo "  PolicyCore     -> http://${BIND_HOST}:${STREAMLIT_PORT}/${BASE_URL_PATH}   (nginx /${BASE_URL_PATH}/)"
echo "  Policy-Service -> http://${BIND_HOST}:${POLICY_SERVICE_PORT}/"
echo "  Claims-Service -> http://${BIND_HOST}:${CLAIMS_SERVICE_PORT}/   (POLICY_SERVICE_URL=${POLICY_SERVICE_URL})"
echo "  UI             -> served by nginx from apps/console/web/dist"
