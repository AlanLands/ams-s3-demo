#!/usr/bin/env bash
# App 4 of 4 — Claims-Service (ClaimsPortal's claims side), Python / FastAPI.
#
# The target of CR-2026-043 (deductible handling). Needs Policy-Service on
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
uvicorn repos.claimsportal.claims_service.main:app --port "${CLAIMS_SERVICE_PORT:-8082}"
