#!/usr/bin/env bash
# S3 Enhancement Delivery — the LEGACY Streamlit console.
#
# The console the demo is actually presented from is the React app at
# apps/console/web/ + api/, started by apps/run-console.sh and opened at
# http://localhost:5173. This script is the older single-file Streamlit view,
# kept as a fallback surface only. Note it defaults to PORT=8501, which is the
# same port demo/run_mockapp.sh / apps/run-policycore.sh serve the PolicyCore
# portal on — set PORT explicitly if you want both up at once.
#
# The MapleSure PolicyCore portal is opened separately by the presenter after
# the generated change applies.
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"
streamlit run s3_enhancement/app.py --server.port "${PORT:-8501}"
