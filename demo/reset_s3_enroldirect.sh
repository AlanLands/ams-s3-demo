#!/usr/bin/env bash
# CR-2026-045 (EnrolDirect target) between-rehearsals reset.
# Same shape as demo/reset_s3_claimsportal.sh, and for a stronger reason: the
# pre-CR baseline comes from the committed-in-place snapshot at
# apps/enroldirect/.baseline/ rather than `git checkout HEAD --`. This CR
# creates no new file, so every path below has a pre-CR counterpart — but the
# baseline for this target is a *removal* (the gate does not classify
# prospects), and restoring it from git would depend on apps/enroldirect/
# being committed at the baseline state rather than at whatever a rehearsal
# last applied.
set -euo pipefail
cd "$(dirname "$0")/.."

# Step 0 (SCM_MODE=live) can leave the repo on a branch this demo cut for a
# previous rehearsal's CR (`feature/AMS-nnn-<target>`, see
# scm.branch_name_for). Those never diverge from main — this pass never
# commits, see s3_enhancement/scm_live.py — so returning to main is safe.
#
# Any other branch is a developer's own work and is left alone.
_current_branch="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$_current_branch" == feature/AMS-* ]] && ! git checkout main 2>/dev/null; then
  echo "note: staying on '$_current_branch' — switching to main would conflict with local changes"
fi

ENROLDIRECT=apps/enroldirect
BASELINE_FILES=(
  applicants.py
  eligibility.py
  enrolments.py
  main.py
)
for f in "${BASELINE_FILES[@]}"; do
  cp "$ENROLDIRECT/.baseline/$f" "$ENROLDIRECT/$f"
done
# Generated test suite — removed entirely on reset.
rm -f tests/test_s3_prospect_access.py

echo "EnrolDirect source baseline restored; generated files removed."
echo "Note: staged proposals under s3_enhancement/out/ are shared with the other targets —"
echo "run demo/reset_s3.sh too for a full between-rehearsals reset."
