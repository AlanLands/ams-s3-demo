#!/usr/bin/env bash
# App 2 of 4 — PolicyCore, the MapleSure policy-administration portal.
#
# This is the "client's application" window: the one the audience watches
# change when an S3 code proposal is applied. Python / Streamlit / SQLite.
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"

echo "  PolicyCore portal -> http://localhost:${PORT:-8501}"
streamlit run apps/policycore/app.py --server.port "${PORT:-8501}"
