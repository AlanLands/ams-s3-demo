#!/usr/bin/env bash
# CR-2026-043 demo beat — the Spring Boot ClaimsPortal services themselves:
# the Policy Team console (:8081) and Claims Team console (:8082) the AI adds
# deductible handling to. Builds if needed, then runs both until Ctrl-C.
set -euo pipefail
cd "$(dirname "$0")/../sandbox/spring-demo"

for svc in policy-service claims-service; do
  if [ ! -f "$svc/target/$svc-1.0.0.jar" ]; then
    (cd "$svc" && mvn -q package -DskipTests)
  fi
done

trap 'kill 0' EXIT
java -jar policy-service/target/policy-service-1.0.0.jar &
java -jar claims-service/target/claims-service-1.0.0.jar &

echo "Policy Team console  -> http://localhost:8081/"
echo "Claims Team console  -> http://localhost:8082/"
echo "Ctrl-C to stop both."
wait
