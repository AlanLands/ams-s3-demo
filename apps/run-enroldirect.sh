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

# Applying a CR rewrites this target's .py files on disk, but a plain uvicorn
# serves the code it imported at startup — so the console shows the change
# applied while :8083 still answers with the baseline, which reads as "the
# change did nothing". Restarting between Apply and Revert is the default cure.
#
# TARGET_RELOAD=1 automates that, scoped to this target's own directory. It is
# OFF by default for two reasons: --reload needs watchfiles, which is not in
# requirements.txt (hard rule 4 — a locked-down install would not have it); and
# the S3 pipeline writes into the very tree being watched, which is why the
# console's own unit forbids --reload outright (deploy/aws/README.md's
# "--reload caveat"). Here the blast radius is one target app rather than the
# pipeline, so it is offered as a switch — but expect a restart mid-Apply, and
# never set it for the console.
RELOAD_ARGS=()
if [ "${TARGET_RELOAD:-0}" = "1" ]; then
  RELOAD_ARGS=(--reload --reload-dir repos/enroldirect)
  echo "  (TARGET_RELOAD=1 — watching repos/enroldirect for applied changes)"
fi
# The ${A[@]+"${A[@]}"} form, not a bare "${A[@]}": macOS ships bash 3.2, where
# an empty array under `set -u` is an unbound-variable error.
uvicorn repos.enroldirect.main:app --port "${ENROLDIRECT_PORT:-8083}" \
  ${RELOAD_ARGS[@]+"${RELOAD_ARGS[@]}"}
