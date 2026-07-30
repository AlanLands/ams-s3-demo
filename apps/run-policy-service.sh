#!/usr/bin/env bash
# App 3 of 4 — Policy-Service (ClaimsPortal's policy side), Python / FastAPI.
#
# Serves policy records to Claims-Service. Start this one BEFORE
# run-claims-service.sh: claims calls policy over HTTP, and a claim filed
# while policy is down fails the lookup.
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"

echo "  Policy-Service -> http://localhost:8081/"
uvicorn apps.claimsportal.policy_service.main:app --port 8081
