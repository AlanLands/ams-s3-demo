#!/usr/bin/env bash
# S3 Enhancement Delivery — the AMS console drives live CR intake, codegen,
# generated tests, and release notes. The MapleSure mockapp is opened separately
# by the presenter after the generated change applies.
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"
streamlit run s3_enhancement/app.py --server.port "${PORT:-8501}"
