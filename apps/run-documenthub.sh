#!/usr/bin/env bash
# App 6 of 6 — DocumentHub, MapleSure's enrolment document service. Python / FastAPI.
#
# Standalone: it holds its enrolment feed in-process and calls no other
# service, so it needs nothing running beside it and nothing beyond the venv.
# Start it on its own to demo the confirmation packs and the selection audit.
#
# The seeded feed contains one record — ENR-20260804-005, Aditi Varma — that is
# on the sponsor's roster and was admitted under guest access. That combination
# has no wording, so the pack falls through to the guest one and tells a
# rostered person we hold no record of them. It is visible on the page, and it
# is what US-2026-046 fixes.
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"

# Port comes from .env (DOCUMENTHUB_PORT), defaulting to 8084 — 8081 and 8082
# belong to ClaimsPortal's two services, 8083 to EnrolDirect, 8501 to PolicyCore.
if [ -f .env ]; then set -a; . ./.env; set +a; fi

echo "  DocumentHub -> http://localhost:${DOCUMENTHUB_PORT:-8084}/"

# Applying a user story rewrites this target's .py files on disk, but a plain uvicorn
# serves the code it imported at startup — so the console shows the change
# applied while :8084 still answers with the baseline, which reads as "the
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
  RELOAD_ARGS=(--reload --reload-dir repos/documenthub)
  echo "  (TARGET_RELOAD=1 — watching repos/documenthub for applied changes)"
fi
# The ${A[@]+"${A[@]}"} form, not a bare "${A[@]}": macOS ships bash 3.2, where
# an empty array under `set -u` is an unbound-variable error.

# Record this shell's PID so the console can restart the app after an Apply.
# Applying rewrites this target's .py files, but a running uvicorn keeps serving
# the code it imported at startup — so without a restart the console reports the
# change applied while the port still answers with the baseline. The console
# only ever stops a process it holds a PID for (admin_ops.owned_pid), and until
# this existed a service started here, in a terminal, could never be one of
# them. `exec` below means this PID *is* uvicorn's, not a parent shell's.
mkdir -p logs
echo $$ > "logs/documenthub.pid"
trap 'rm -f "logs/documenthub.pid"' EXIT

exec uvicorn repos.documenthub.main:app --port "${DOCUMENTHUB_PORT:-8084}" \
  ${RELOAD_ARGS[@]+"${RELOAD_ARGS[@]}"}
