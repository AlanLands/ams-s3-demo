#!/usr/bin/env bash
# App 4 of 4 — Claims-Service (ClaimsPortal's claims side), Python / FastAPI.
#
# The target of CR-2026-043 (deductible handling). Needs Policy-Service on
# :8081 already running — see run-policy-service.sh.
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"

echo "  Claims-Service -> http://localhost:8082/"
uvicorn apps.claimsportal.claims_service.main:app --port 8082
