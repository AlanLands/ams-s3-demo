#!/usr/bin/env bash
# Serves the MapleSure mockapp itself — the "client's app" window for both
# mockapp CR beats: CR-2026-041 (coverage tier) and CR-2026-042 (the "Request
# a Policy Endorsement" form the AI adds a 6th field, Priority, to). Formerly
# run_s4_endorsement.sh; the s4 in that name was a leftover from the
# six-scenario repo, not a scenario this project has.
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"
# Same base path as apps/run-policycore.sh — the two launchers must agree or
# MOCKAPP_URL / VITE_MOCKAPP_URL point at a 404 depending on which one ran.
if [ -f .env ]; then set -a; . ./.env; set +a; fi
streamlit run apps/policycore/app.py \
    --server.port "${PORT:-8501}" \
    --server.baseUrlPath "${STREAMLIT_BASE_URL_PATH:-sl_policycore}"
