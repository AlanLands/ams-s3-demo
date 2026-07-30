#!/usr/bin/env bash
# Start both MapleSure demo services; Ctrl-C stops them both.
set -euo pipefail
cd "$(dirname "$0")/../.."
source .venv/bin/activate
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"

trap 'kill 0' EXIT

uvicorn apps.claimsportal.policy_service.main:app --port 8081 &
uvicorn apps.claimsportal.claims_service.main:app --port 8082 &

echo "policy_service  -> http://localhost:8081/api/policies"
echo "claims_service  -> http://localhost:8082/api/claims"
echo "Ctrl-C to stop both."
wait
