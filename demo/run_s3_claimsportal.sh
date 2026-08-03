#!/usr/bin/env bash
# CR-2026-043 "Benefit Claim Deductible Handling" — the ClaimsPortal services
# themselves: the Contracts Team console (:8081, "MapleSure — Group Contracts")
# and the Claims Team console (:8082, "MapleSure — Benefit Claims") the AI adds
# deductible handling to. Runs both until Ctrl-C.
#
# Equivalent to running apps/run-policy-service.sh and apps/run-claims-service.sh
# in two terminals; this starts the pair in one.
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"

trap 'kill 0' EXIT
uvicorn repos.claimsportal.policy_service.main:app --port 8081 &
uvicorn repos.claimsportal.claims_service.main:app --port 8082 &

echo "Contracts Team console  -> http://localhost:8081/"
echo "Claims Team console  -> http://localhost:8082/"
echo "Ctrl-C to stop both."
wait
