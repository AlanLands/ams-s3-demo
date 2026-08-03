#!/usr/bin/env bash
# App 4 of 5 — Claims-Service (ClaimsPortal's claims side), Python / FastAPI.
#
# The target of US-2026-043 (deductible handling). Needs Policy-Service on
# :8081 already running — see run-policy-service.sh.
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"

# .env supplies CLAIMS_SERVICE_PORT and POLICY_SERVICE_URL — the latter is
# read by claims_service/policy_client.py for its policy lookups.
if [ -f .env ]; then set -a; . ./.env; set +a; fi

echo "  Claims-Service -> http://localhost:${CLAIMS_SERVICE_PORT:-8082}/"
echo "  validating policies against ${POLICY_SERVICE_URL:-http://localhost:8081}"

# Record this shell's PID so the console can restart the app after an Apply.
# Applying rewrites this target's .py files, but a running uvicorn keeps serving
# the code it imported at startup — so without a restart the console reports the
# change applied while the port still answers with the baseline. The console
# only ever stops a process it holds a PID for (admin_ops.owned_pid), and until
# this existed a service started here, in a terminal, could never be one of
# them. `exec` below means this PID *is* uvicorn's, not a parent shell's.
mkdir -p logs
echo $$ > "logs/claims_service.pid"
trap 'rm -f "logs/claims_service.pid"' EXIT

exec uvicorn repos.claimsportal.claims_service.main:app --port "${CLAIMS_SERVICE_PORT:-8082}"
