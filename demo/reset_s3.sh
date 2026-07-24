#!/usr/bin/env bash
# S3's demo beat mutates mockapp source files and SQLite state. Restore the
# pre-codegen mockapp files from the baseline tag, remove generated runtime
# artifacts, then reseed to restore pristine policy/claim state between rehearsals.
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate
git show s3-baseline:mockapp/app.py > mockapp/app.py
git show s3-baseline:mockapp/core/models.py > mockapp/core/models.py
git show s3-baseline:mockapp/core/db.py > mockapp/core/db.py
rm -f mockapp/core/coverage.py tests/test_s3_coverage_upgrade.py
python -m mockapp.core.seed
rm -rf .cache/llm
# Every staged proposal (Generate/Ask/Apply's working state) and harness run,
# not just harness subdirs — s3_enhancement/out/ is gitignored/regenerated
# per run, so a "between rehearsals" reset should leave none of it behind.
rm -rf s3_enhancement/out/*
rm -f data/ticket_events.jsonl
# Board workflow transitions (analysis -> In Progress, QA hand-off, Done)
# persist into the committed per-issue Jira replay caches via
# _update_get_issue_cache — restore them so every rehearsal starts from the
# seeded To Do / In Progress board, not wherever the last run ended.
git checkout -- 's3_enhancement/cache/jira_*.json' 2>/dev/null || true
# Lets the AMS console (which caches per-ticket analysis/proposal results in
# the browser's localStorage) detect that server state was just reset and
# drop its stale cache instead of continuing to show it — see
# common.ticket_events.events_log_marker().
mkdir -p data
date +%s%N > data/.s3_reset_marker
echo "S3 source baseline restored, mockapp reseeded, LLM cache cleared, and ticket timeline cleared."
