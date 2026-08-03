#!/usr/bin/env bash
# App 3 of 5 — Policy-Service (ClaimsPortal's policy side), Python / FastAPI.
#
# Serves policy records to Claims-Service. Start this one BEFORE
# run-claims-service.sh: claims calls policy over HTTP, and a claim filed
# while policy is down fails the lookup.
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"

# Port comes from .env (POLICY_SERVICE_PORT). If you change it, also point
# POLICY_SERVICE_URL at the new port — that's the URL Claims-Service calls.
if [ -f .env ]; then set -a; . ./.env; set +a; fi

echo "  Policy-Service -> http://localhost:${POLICY_SERVICE_PORT:-8081}/"

# Record this shell's PID so the console can restart the app after an Apply.
# Applying rewrites this target's .py files, but a running uvicorn keeps serving
# the code it imported at startup — so without a restart the console reports the
# change applied while the port still answers with the baseline. The console
# only ever stops a process it holds a PID for (admin_ops.owned_pid), and until
# this existed a service started here, in a terminal, could never be one of
# them. `exec` below means this PID *is* uvicorn's, not a parent shell's.
mkdir -p logs
echo $$ > "logs/policy_service.pid"
trap 'rm -f "logs/policy_service.pid"' EXIT

exec uvicorn repos.claimsportal.policy_service.main:app --port "${POLICY_SERVICE_PORT:-8081}"
