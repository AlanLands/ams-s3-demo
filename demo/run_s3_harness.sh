#!/usr/bin/env bash
# S3 Option C — agent-harness codegen beat (the "money shot"). Presenter opens
# this in a second terminal pane before the demo starts and sits at the prompt
# below; "one keypress" means pressing Enter here at the scripted moment
# (beat 4 in demo/presenter_notes/s3_enhancement.md), right after beats 1-2
# (impact analysis, effort estimate) finish in the console launched by
# apps/run-console.sh (the React console on :5173 — demo/run_s3.sh is the
# older Streamlit fallback).
#
# Replay-primary (CLAUDE.md demo-reliability rule): the default invocation
# replays the rehearsed recording — deterministic, offline, cannot fail live.
# Pass --live to run the real agent CLI instead (rehearsals, or demo-day
# showmanship if the room is warm and the schedule is ahead). A live run
# records itself (HARNESS_MODE defaults to "record"), so every rehearsal
# refreshes the recording the demo-day replay depends on.
#
# HARNESS_MODE=live|record|replay (default record), mirroring LLM_MODE.
# AGENT_HARNESS=claude|codex (default claude) picks which CLI runs a live beat.
#
# If a --live run fails, this is a visible, presenter-decided moment — rerun
# in the same pane without --live to fall back to the recording, or abandon
# the beat and use the console "Generate the change" / "Generate tests + run"
# buttons (the unmodified pipeline, itself replay-primary).
#
# A --live run edits repos/policycore/ in the working tree. The usual way back
# is demo/reset_s3.sh, which is broken until the repos/ move is committed —
# see the note at the top of that script before you rehearse the live path.
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"

MODE="replay"
if [[ "${1:-}" == "--live" ]]; then
  MODE="run"
  shift
elif [[ "${1:-}" == "--replay" ]]; then
  # accepted for compatibility with older notes/muscle memory — already the default
  shift
fi

TIER_NAME="${1:-Elite}"

if [[ "$MODE" == "run" ]]; then
  read -r -p "Press Enter to launch the agent harness live against PolicyCore (tier: ${TIER_NAME})..." _
else
  echo "Replaying the rehearsed harness recording (tier: ${TIER_NAME})..."
fi

python -m s3_enhancement.harness "$MODE" --tier-name "$TIER_NAME"
