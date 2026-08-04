#!/usr/bin/env bash
# US-2026-046 ("Confirmation Pack Wording For Rostered Applicants Admitted As
# Guests") between-rehearsals reset.
#
# Same shape as demo/reset_s3_enroldirect.sh, and for the same reason: the
# pre-user story baseline comes from the committed-in-place snapshot at
# repos/documenthub/.baseline/ rather than `git checkout HEAD --`. Restoring
# from git would depend on repos/documenthub/ being committed at the baseline
# state rather than at whatever a rehearsal last applied.
#
# Only the three codegen_allowlist files are restored. feed.py, main.py and
# static/index.html are outside the user story's blast radius by declaration
# (see .s3targets.json), so a rehearsal cannot have moved them — and quietly
# restoring a file the pipeline was never allowed to touch would hide a real
# edit somebody made on purpose.
set -euo pipefail
cd "$(dirname "$0")/.."

# Step 0 (SCM_MODE=live) can leave the repo on a branch this demo cut for a
# previous rehearsal's user story (`feature/AMS-nnn-<target>`, see
# scm.branch_name_for). Those never diverge from main — this pass never
# commits, see s3_enhancement/scm_live.py — so returning to main is safe.
#
# Any other branch is a developer's own work and is left alone.
_current_branch="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$_current_branch" == feature/AMS-* ]] && ! git checkout main 2>/dev/null; then
  echo "note: staying on '$_current_branch' — switching to main would conflict with local changes"
fi

DOCUMENTHUB=repos/documenthub
BASELINE_FILES=(
  wording.py
  enclosures.py
  packs.py
)
for f in "${BASELINE_FILES[@]}"; do
  cp "$DOCUMENTHUB/.baseline/$f" "$DOCUMENTHUB/$f"
done
# Generated test suite — removed entirely on reset.
rm -f tests/test_s3_rostered_guest_wording.py

echo "DocumentHub source baseline restored; generated files removed."
echo "Note: staged proposals under s3_enhancement/out/ are shared with the other targets —"
echo "run demo/reset_s3.sh too for a full between-rehearsals reset."
