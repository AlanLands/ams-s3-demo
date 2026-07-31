#!/usr/bin/env bash
# App 2 of 4 — PolicyCore, the MapleSure policy-administration portal.
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
streamlit run apps/policycore/app.py \
    --server.port "${PORT:-8501}" \
    --server.baseUrlPath "${BASE_URL_PATH}"
