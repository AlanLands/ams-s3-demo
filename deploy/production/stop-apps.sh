#!/usr/bin/env bash
# Stops everything deploy/production/start-apps.sh started, via its PID files.
#
# Deliberately not `set -e`: one already-dead service must not stop the loop
# from cleaning up the other three.
set -uo pipefail
cd "$(dirname "$0")/../.."

for name in console-api policycore policy-service claims-service; do
  pidfile="logs/$name.pid"
  if [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
    kill "$(cat "$pidfile")" && echo "  stopped $name (pid $(cat "$pidfile"))"
  else
    echo "  $name not running"
  fi
  rm -f "$pidfile"
done
