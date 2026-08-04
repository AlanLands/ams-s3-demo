#!/usr/bin/env bash
# Starts all five backend processes detached, one PID file each under logs/.
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
ENROLDIRECT_PORT="${ENROLDIRECT_PORT:-20115}"
DOCUMENTHUB_PORT="${DOCUMENTHUB_PORT:-20116}"
BASE_URL_PATH="${STREAMLIT_BASE_URL_PATH:-sl_policycore}"
BIND_HOST="${BIND_HOST:-127.0.0.1}"
# Claims-Service dials this for policy lookups; default it to whatever port
# Policy-Service actually got above rather than a second hard-coded number.

mkdir -p logs

# PID-file names overlap the console admin panel's, which writes
# logs/{service_id}.pid for the same apps (s3_enhancement/admin_ops.py,
# SERVICES). Every surviving app is spelled identically in both. So on a host
# running both, stop-apps.sh can kill a process the panel started and believes
# it owns — its owned_pid() is a PID file, not a process scan. The two are
# meant for different hosts (this script for a deployed box, the panel for the
# presenter's machine); run only one per host and the overlap is moot.
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

start policycore python -m streamlit run repos/policycore/app.py \
    --server.port "$STREAMLIT_PORT" \
    --server.address "$BIND_HOST" \
    --server.baseUrlPath "$BASE_URL_PATH" \
    --server.headless true \
    --browser.gatherUsageStats false

# EnrolDirect (US-2026-045's target) and DocumentHub (US-2026-046's) both call
# no other service and seed themselves in-process, so neither has an ordering
# constraint against the two above or each other. No --reload here, unlike the
# apps/run-*.sh TARGET_RELOAD switch: a detached process restarting mid-Apply
# has no terminal to say so on.
start enroldirect python -m uvicorn repos.enroldirect.main:app \
    --host "$BIND_HOST" --port "$ENROLDIRECT_PORT"

start documenthub python -m uvicorn repos.documenthub.main:app \
    --host "$BIND_HOST" --port "$DOCUMENTHUB_PORT"

echo
echo "  Console API    -> http://${BIND_HOST}:${API_PORT}                    (nginx /api/)"
echo "  PolicyCore     -> http://${BIND_HOST}:${STREAMLIT_PORT}/${BASE_URL_PATH}   (nginx /${BASE_URL_PATH}/)"
echo "  EnrolDirect    -> http://${BIND_HOST}:${ENROLDIRECT_PORT}/"
echo "  DocumentHub    -> http://${BIND_HOST}:${DOCUMENTHUB_PORT}/"
echo "  UI             -> served by nginx from apps/console/web/dist"
