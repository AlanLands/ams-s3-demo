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
uvicorn repos.claimsportal.policy_service.main:app --port "${POLICY_SERVICE_PORT:-8081}"
