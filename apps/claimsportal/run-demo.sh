#!/usr/bin/env bash
# Start both MapleSure demo services; Ctrl-C stops them both.
set -euo pipefail
cd "$(dirname "$0")"

trap 'kill 0' EXIT

(cd policy-service && mvn -q spring-boot:run) &
(cd claims-service && mvn -q spring-boot:run) &

echo "policy-service  -> http://localhost:8081/api/policies"
echo "claims-service  -> http://localhost:8082/api/claims"
echo "Ctrl-C to stop both."
wait
