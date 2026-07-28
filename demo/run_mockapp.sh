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
streamlit run apps/policycore/app.py --server.port "${PORT:-8501}"
