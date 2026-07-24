#!/usr/bin/env bash
# CR-2026-043 demo beat — the Spring Boot ClaimsPortal services themselves:
# the Policy Team console (:8081) and Claims Team console (:8082) the AI adds
# deductible handling to. Builds if needed, then runs both until Ctrl-C.
set -euo pipefail
cd "$(dirname "$0")/../sandbox/spring-demo"

# Always rebuild: an existing jar may predate a just-applied S3 change, and
# serving stale code silently breaks the before/after demo beat. With a warm
# local Maven repo this is seconds, not minutes.
for svc in policy-service claims-service; do
  (cd "$svc" && mvn -q package -DskipTests)
done

trap 'kill 0' EXIT
java -jar policy-service/target/policy-service-1.0.0.jar &
java -jar claims-service/target/claims-service-1.0.0.jar &

echo "Policy Team console  -> http://localhost:8081/"
echo "Claims Team console  -> http://localhost:8082/"
echo "Ctrl-C to stop both."
wait
