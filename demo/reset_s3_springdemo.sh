#!/usr/bin/env bash
# CR-2026-043 (ClaimsPortal target) between-rehearsals reset.
# Mirrors demo/reset_s3.sh's job for the mockapp target: the pre-CR baseline
# is restored from the committed-in-place snapshot at
# apps/claimsportal/.baseline/ rather than `git checkout HEAD --`, since the
# generated claim_rules.py has no pre-CR counterpart to check out.
set -euo pipefail
cd "$(dirname "$0")/.."

# Step 0 (SCM_MODE=live) can leave the repo on a real feature branch cut for
# a previous rehearsal's CR — see the same note in demo/reset_s3.sh. Best-
# effort and non-fatal: a developer running this from their own work branch
# must not have this step abort the restore below.
_current_branch="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$_current_branch" != "main" ]] && ! git checkout main 2>/dev/null; then
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
