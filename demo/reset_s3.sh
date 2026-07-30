#!/usr/bin/env bash
# S3's demo beat mutates mockapp source files and SQLite state. Restore the
# pre-codegen mockapp files from the baseline tag, remove generated runtime
# artifacts, then reseed to restore pristine policy/claim state between rehearsals.
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate
# Step 0 (SCM_MODE=live) can leave the repo on a real feature branch cut for
# a previous rehearsal's CR — those never diverge from main (this pass never
# commits, see s3_enhancement/scm_live.py), so returning to main is safe
# there. Best-effort only, and deliberately not fatal: a developer running
# this from their own long-lived work branch (real, unrelated uncommitted
# changes) must not have this step abort the restore below, which is the
# part of this script that actually matters.
_current_branch="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$_current_branch" != "main" ]] && ! git checkout main 2>/dev/null; then
  echo "note: staying on '$_current_branch' — switching to main would conflict with local changes"
fi
# Restored from HEAD, not from the `s3-baseline` tag — see the same note in
# demo/reset_s3_endorsement.sh. The tag predates both the apps/ restructure
# (its paths are `mockapp/...`, which no longer resolve) and the endorsements
# table (its `wipe_db()` drops `policies` while `endorsements` still
# references it, so reseeding fails with a FOREIGN KEY error and the reset
# can never finish).
git checkout HEAD -- \
  apps/policycore/app.py \
  apps/policycore/core/models.py \
  apps/policycore/core/db.py
rm -f apps/policycore/core/coverage.py tests/test_s3_coverage_upgrade.py
python -m apps.policycore.core.seed
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
