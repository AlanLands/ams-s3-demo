#!/usr/bin/env bash
# CR-2026-043 (ClaimsPortal target) between-rehearsals reset.
# Mirrors demo/reset_s3.sh's job for the mockapp target: the pre-CR baseline
# is restored from the committed-in-place snapshot at
# apps/claimsportal/.baseline/ rather than `git checkout HEAD --`, since the
# generated claim_rules.py has no pre-CR counterpart to check out.
set -euo pipefail
cd "$(dirname "$0")/.."

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

CLAIMSPORTAL=apps/claimsportal
BASELINE_FILES=(
  policy_service/policy.py
  policy_service/main.py
  claims_service/claim.py
  claims_service/policy_client.py
  claims_service/main.py
)
for f in "${BASELINE_FILES[@]}"; do
  cp "$CLAIMSPORTAL/.baseline/$f" "$CLAIMSPORTAL/$f"
done
# Files the CR creates from scratch — removed entirely on reset.
rm -f "$CLAIMSPORTAL/claims_service/claim_rules.py"
rm -f tests/test_s3_claims_deductible.py

echo "ClaimsPortal source baseline restored; generated files removed."
echo "Note: staged proposals under s3_enhancement/out/ are shared with the mockapp target —"
echo "run demo/reset_s3.sh too for a full between-rehearsals reset."
