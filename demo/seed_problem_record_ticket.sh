#!/usr/bin/env bash
# Creates one demo ticket tagged origin=problem_record on the live board —
# see seed_problem_record_ticket.py for what/why. Requires the API server
# (uvicorn api.main:app) already running.
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate
python demo/seed_problem_record_ticket.py
