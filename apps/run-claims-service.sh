#!/usr/bin/env bash
# App 4 of 4 — Claims-Service (ClaimsPortal's claims side), Java / Spring Boot.
#
# The target of CR-2026-043 (deductible handling). Needs Policy-Service on
# :8081 already running — see run-policy-service.sh.
set -euo pipefail
cd "$(dirname "$0")/claimsportal/claims-service"

mvn -q package -DskipTests
echo "  Claims-Service -> http://localhost:8082/"
java -jar target/claims-service-1.0.0.jar
