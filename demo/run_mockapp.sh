#!/usr/bin/env bash
# Serves the MapleSure PolicyCore portal itself — the "client's app" window
# for both PolicyCore user story beats: US-2026-041 "Plan Tier Upgrade Option" and
# US-2026-042 "Amendment Priority Field" (the "Request a Contract Amendment"
# form the AI adds a 6th field, Priority, to; it has 5 at baseline).
#
# Same job as apps/run-policycore.sh — either launcher works. Formerly
# run_s4_endorsement.sh; the s4 in that name was a leftover from the
# six-scenario repo, not a scenario this project has. The source it serves
# now lives under repos/, which is the folder holding what S3 *changes*;
# apps/ holds the console and the launchers, which do the changing.
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"
# Same base path as apps/run-policycore.sh — the two launchers must agree or
# MOCKAPP_URL / VITE_MOCKAPP_URL point at a 404 depending on which one ran.
if [ -f .env ]; then set -a; . ./.env; set +a; fi
streamlit run repos/policycore/app.py \
    --server.port "${PORT:-8501}" \
    --server.baseUrlPath "${STREAMLIT_BASE_URL_PATH:-sl_policycore}"
