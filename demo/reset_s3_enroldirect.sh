#!/usr/bin/env bash
# US-2026-045 ("Prospect Member Eligibility Check For Online Enrolment",
# board ticket AMS-1045 — opened automatically from stories/US-2026-045.md, not
# seeded by any script) between-rehearsals reset.
# Same shape as demo/reset_s3_documenthub.sh, and for a stronger reason: the
# pre-user story baseline comes from the committed-in-place snapshot at
# repos/enroldirect/.baseline/ rather than `git checkout HEAD --`. This user story
# creates no new file, so every path below has a pre-user story counterpart — but the
# baseline for this target is a *removal* (the gate does not classify
# prospects), and restoring it from git would depend on repos/enroldirect/
# being committed at the baseline state rather than at whatever a rehearsal
# last applied.
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

ENROLDIRECT=repos/enroldirect
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
