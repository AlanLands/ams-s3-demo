#!/usr/bin/env bash
# App 2 of 5 — PolicyCore, the MapleSure policy-administration portal.
#
# This is the "client's application" window: the one the audience watches
# change when an S3 code proposal is applied. Python / Streamlit / SQLite.
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"

# Served under a base path so it can share a host/reverse proxy with the
# other apps in a production deployment. Override via STREAMLIT_BASE_URL_PATH
# in .env; keep MOCKAPP_URL (and the frontend's VITE_MOCKAPP_URL) in sync.
if [ -f .env ]; then set -a; . ./.env; set +a; fi
BASE_URL_PATH="${STREAMLIT_BASE_URL_PATH:-sl_policycore}"

echo "  PolicyCore portal -> http://localhost:${PORT:-8501}/${BASE_URL_PATH}"

# Record this shell's PID so the console can restart the app after an Apply.
# Applying rewrites this target's .py files, but a running uvicorn keeps serving
# the code it imported at startup — so without a restart the console reports the
# change applied while the port still answers with the baseline. The console
# only ever stops a process it holds a PID for (admin_ops.owned_pid), and until
# this existed a service started here, in a terminal, could never be one of
# them. `exec` below means this PID *is* uvicorn's, not a parent shell's.
mkdir -p logs
echo $$ > "logs/policycore.pid"
trap 'rm -f "logs/policycore.pid"' EXIT

exec streamlit run repos/policycore/app.py \
    --server.port "${PORT:-8501}" \
    --server.baseUrlPath "${BASE_URL_PATH}"
