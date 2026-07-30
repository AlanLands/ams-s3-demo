#!/usr/bin/env bash
# CR-2026-042's demo beat mutates mockapp source files. Restore the
# pre-codegen mockapp files from the baseline tag, remove the generated test
# file, then reseed to restore pristine policy/claim/endorsement state.
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate

# Step 0 (SCM_MODE=live) can leave the repo on a real feature branch cut for
# a previous rehearsal's CR — see the same note in demo/reset_s3.sh. Best-
# effort and non-fatal: a developer running this from their own work branch
# must not have this step abort the restore below.
_current_branch="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$_current_branch" != "main" ]] && ! git checkout main 2>/dev/null; then
  echo "note: staying on '$_current_branch' — switching to main would conflict with local changes"
fi

# Restored from HEAD, not from the `s3-endorsement-baseline` tag.
#
# Two reasons. The tag predates the apps/ restructure, so every path in it
# (`mockapp/...`) no longer exists — `git show <tag>:apps/policycore/app.py`
# fails outright. And the tag's `db.py` predates the endorsements table, so its
# `wipe_db()` drops `policies` while `endorsements` still references it: once
# any rehearsal has created that table, reseeding dies on a FOREIGN KEY error
# and the reset can never complete again.
#
# `git checkout` also removes the old hazard this guard existed for:
# `git show <missing-ref>:file > file` truncates the file via the shell
# redirect *before* git runs and fails, destroying the source it was meant to
# restore. `git checkout` writes only on success.
git checkout HEAD -- \
  apps/policycore/app.py \
  apps/policycore/core/models.py \
  apps/policycore/core/db.py \
  apps/policycore/core/endorsements.py
rm -f tests/test_s3_endorsement_priority.py
python -m apps.policycore.core.seed
rm -rf .cache/llm
echo "CR-2026-042 source baseline restored, mockapp reseeded, and LLM cache cleared."
