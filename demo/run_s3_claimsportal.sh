#!/usr/bin/env bash
# CR-2026-043 demo beat — the ClaimsPortal services themselves: the Policy
# Team console (:8081) and Claims Team console (:8082) the AI adds deductible
# handling to. Runs both until Ctrl-C.
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"

trap 'kill 0' EXIT
uvicorn apps.claimsportal.policy_service.main:app --port 8081 &
uvicorn apps.claimsportal.claims_service.main:app --port 8082 &

echo "Policy Team console  -> http://localhost:8081/"
echo "Claims Team console  -> http://localhost:8082/"
echo "Ctrl-C to stop both."
wait
