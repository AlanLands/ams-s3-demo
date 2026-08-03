#!/usr/bin/env bash
# Puts AMS-104 — the ticket whose CR (CR-2026-044, "Flag Urgent Amendment
# Requests") names no target system, forcing S3 to pick the repo — back on the
# board. See seed_s3_repo_selection_ticket.py.
# Needs no running server; run it after demo/reset_s3.sh, which restores the
# committed Jira replay caches and would otherwise drop this ticket.
#
# This is the only ticket still seeded by hand, and only because its beat needs
# a specific pre-set assignee. Every other CR under crs/ opens its own board
# ticket — keyed off the CR id and landing unassigned, so the manager routes it
# (CR-2026-045 -> AMS-1045). See s3_enhancement/cr_intake.py.
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate
# Run as a module so the repo root (cwd) lands on sys.path — this script
# imports `common.jira_client` directly rather than going through the API.
python -m demo.seed_s3_repo_selection_ticket
