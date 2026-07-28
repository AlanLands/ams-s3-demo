#!/usr/bin/env bash
# CR-2026-043 (Spring Boot ClaimsPortal target) between-rehearsals reset.
# Mirrors demo/reset_s3.sh's job for the mockapp target, but apps/claimsportal
# is not git-tracked, so the pre-CR baseline is restored from the committed-in-place
# snapshot at apps/claimsportal/.baseline/ instead of a git tag.
set -euo pipefail
cd "$(dirname "$0")/.."

SPRING=apps/claimsportal
BASELINE_FILES=(
  policy-service/src/main/java/com/maplesure/policy/Policy.java
  policy-service/src/main/java/com/maplesure/policy/PolicyController.java
  claims-service/src/main/java/com/maplesure/claims/Claim.java
  claims-service/src/main/java/com/maplesure/claims/PolicyClient.java
  claims-service/src/main/java/com/maplesure/claims/ClaimsController.java
)
for f in "${BASELINE_FILES[@]}"; do
  cp "$SPRING/.baseline/$f" "$SPRING/$f"
done
# Files the CR creates from scratch — removed entirely on reset.
rm -f "$SPRING/claims-service/src/main/java/com/maplesure/claims/ClaimRules.java"
rm -f "$SPRING/claims-service/src/test/java/com/maplesure/claims/ClaimRulesTest.java"
# Stale Maven build output of the enhanced code.
rm -rf "$SPRING/policy-service/target" "$SPRING/claims-service/target"

echo "Spring demo (ClaimsPortal) source baseline restored; generated files and build output removed."
echo "Note: staged proposals under s3_enhancement/out/ are shared with the mockapp target —"
echo "run demo/reset_s3.sh too for a full between-rehearsals reset."
