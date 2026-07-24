#!/usr/bin/env bash
# CR-2026-042 demo beat — the MapleSure mockapp itself, showing the "Request
# a Policy Endorsement" form the AI adds a 6th field (Priority) to, live.
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"
streamlit run mockapp/app.py --server.port "${PORT:-8501}"
