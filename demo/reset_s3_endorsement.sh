#!/usr/bin/env bash
# CR-2026-042 ("Amendment Priority Field") mutates PolicyCore source files.
# Restore the pre-codegen PolicyCore files from HEAD (not from the tag — see
# the note above the checkout below), remove the generated test file, then
# reseed to restore pristine contract/claim/amendment state.
#
# The filename still says "endorsement" on purpose: teammates invoke this
# script by name, so the 2026-08-03 GRS reskin (endorsement -> amendment)
# changed only its contents. The git tag `s3-endorsement-baseline` and the
# cache namespace `endorsement_field_add` likewise keep their old spelling —
# those are cache identity, and renaming either is a replay miss.
#
# ⚠ KNOWN BROKEN as of 2026-08-03, same as demo/reset_s3.sh: the
# `git checkout HEAD -- repos/policycore/...` below fails with "pathspec did
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate

# Step 0 (SCM_MODE=live) can leave the repo on a branch this demo cut for a
# previous rehearsal's CR (`feature/AMS-nnn-<target>`, see
# scm.branch_name_for). Those never diverge from main — this pass never
# commits, see s3_enhancement/scm_live.py — so returning to main is safe.
#
# Any other branch is a developer's own work and is left alone. The guard used
# to be "try main, carry on if it fails", which is wrong: with a clean tree
# `git checkout main` SUCCEEDS, and every restore below would then come from
# main rather than the branch under test, silently reverting it.
_current_branch="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$_current_branch" == feature/AMS-* ]] && ! git checkout main 2>/dev/null; then
  echo "note: staying on '$_current_branch' — switching to main would conflict with local changes"
fi

# Restored from HEAD, not from the `s3-endorsement-baseline` tag.
#
# Two reasons. The tag predates every directory move this repo has had, so
# every path in it (`mockapp/...`) no longer exists — `git show
# <tag>:repos/policycore/app.py` fails outright. And the tag's `db.py`
# predates the amendments table, so its
# `wipe_db()` drops `policies` while the amendment table — named
# `endorsements` before the 2026-08-03 GRS reskin — still references it: once
# any rehearsal has created that table, reseeding dies on a FOREIGN KEY error
# and the reset can never complete again.
#
# `git checkout` also removes the old hazard this guard existed for:
# `git show <missing-ref>:file > file` truncates the file via the shell
# redirect *before* git runs and fails, destroying the source it was meant to
# restore. `git checkout` writes only on success.
git checkout HEAD -- \
  repos/policycore/app.py \
  repos/policycore/core/models.py \
  repos/policycore/core/db.py \
  repos/policycore/core/amendments.py
rm -f tests/test_s3_amendment_priority.py
python -m repos.policycore.core.seed
rm -rf .cache/llm
echo "CR-2026-042 source baseline restored, PolicyCore reseeded, and LLM cache cleared."
