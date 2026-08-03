#!/usr/bin/env bash
# App 5 of 5 — EnrolDirect, MapleSure's online enrolment channel. Python / FastAPI.
#
# Standalone: it seeds its contracts and applicants in-process and calls no
# other service, so it needs nothing running beside it and nothing beyond the
# venv. Start it on its own to demo the enrolment access gate and the prospect
# impact analysis.
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"

# Port comes from .env (ENROLDIRECT_PORT), defaulting to 8083 — 8081 and 8082
# belong to ClaimsPortal's two services, 8501 to PolicyCore.
if [ -f .env ]; then set -a; . ./.env; set +a; fi

echo "  EnrolDirect -> http://localhost:${ENROLDIRECT_PORT:-8083}/"
uvicorn repos.enroldirect.main:app --port "${ENROLDIRECT_PORT:-8083}"
