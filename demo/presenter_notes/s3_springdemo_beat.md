# S3 — ClaimsPortal beat (second target, ~8 min)

**Point being made**: S3 is a pipeline, not a party trick tuned to one app.
Same console, same beats, a second independently-registered repo/target,
second CR. (Until 2026-07-30 this beat also carried a second-language story —
ClaimsPortal was Java/Spring Boot, verified via `mvn test`/JUnit. It was
rebuilt in Python/FastAPI so the demo runs without a JVM/Maven; the pipeline
now speaks pytest end to end across all three scenarios. What this beat
proves today is a second real repo the pipeline generalizes to, not a second
tech stack.)

**Cast**: `apps/claimsportal` = "ClaimsPortal". policy_service (:8081, Policy
Team console) serves policies; claims_service (:8082, Claims Team console)
validates each submitted claim by calling policy_service over REST. CR-2026-043
(`apps/claimsportal/crs/CR-2026-043.md`, Jira AMS-103, assignee Ravi Kumar)
adds a per-policy deductible: below-deductible claims are rejected, accepted
claims record a payable amount. Fixed contract: `claim_rules.decide`/`payable`
module-level functions.

## Pre-flight (before the audience is in the room)

```bash
./demo/reset_s3.sh              # shared state: out/, ticket events, .cache/llm
./demo/reset_s3_springdemo.sh   # ClaimsPortal back to pre-CR baseline
uvicorn apps.console.api.main:app --port 8000  # terminal 1 — API :8000 (never --reload:
                                  # Generate/Apply write .py files, the watcher
                                  # restarts, and your login session 401s)
(cd apps/console/web && npm run dev)    # terminal 2 — console :5173
./demo/run_s3_springdemo.sh     # terminal 3 — both team consoles :8081/:8082
```

Check: :8081 policies show **no Deductible**; claims console accepts an
80-dollar claim on MS-1004 (this exact claim gets rejected later — the
before/after moment). Make sure no stale service holds 8081/8082
(`pkill -f 'policy_service|claims_service'` first if in doubt) — a stale
process serves the OLD behavior and silently ruins the after-beat.

## Beats

1. **Before**: Policy Team console (:8081) and Claims Team console (:8082).
   Submit an 80-dollar claim on MS-1004 → ACCEPTED. "Small claims below any
   deductible sail through to adjusters today."
2. **Console** (:5173, log in Ravi Kumar / 1001): open **AMS-103** on the
   board. This is a second registered target — the file-selection panel
   scopes to ClaimsPortal's own pool (5 Python files).
3. **Impact analysis + effort**: drafted against the real sources — names
   policy.py / policy_client.py's PolicyView / a new claim_rules module.
4. **Generate**: diff spans BOTH services — the model gains `deductible`
   on the policy side and the consuming field on the claims side, plus the
   new claim_rules.py. Point out reasons-per-file, then **Apply**.
5. **Design doc + QA hand-off**: the workflow is real Jira discipline, live
   on the board — running the analysis already moved the card
   To Do → In Progress automatically. After Apply, draft the design doc: it
   renders as an actual MapleSure letterhead document, downloadable as
   .html/.md ("this is the artifact QA receives"). Then hand off: pick a
   tester (Priya Nair, passcode 1003, or Tom Becker, 1004) → the card moves
   to the **QA column**, assigned to them, and the developer is now locked
   out of the test step (show the lock hint).
6. **Generate tests, as the tester**: log out, log in as the tester, open
   the ticket from the QA column, run "Generate tests + run": a pytest suite
   (`tests/test_s3_claims_deductible.py`) — same runner as scenarios 1 and 2.
   All green.
7. **After**: restart the services (Ctrl-C terminal 3, rerun
   `./demo/run_s3_springdemo.sh`), resubmit the
   same 80-dollar claim on MS-1004 → **REJECTED_BELOW_DEDUCTIBLE**; a
   1,200-dollar claim on MS-1001 → ACCEPTED with **payableAmount 700**.
8. **Release notes** (still as the tester), then "QA passed — mark ticket
   Done" closes the loop on the board.

## Fallbacks

- All generative beats replay from committed recordings
  (`s3_enhancement/cache/*spring_claims_deductible*`, plus `.cache/llm` once
  warmed) — with `LLM_MODE=replay` (the default) the whole flow runs offline.
  `reset_s3.sh` wipes `.cache/llm`, so either re-warm the narrative beats in
  rehearsal or skip that wipe on demo day.
- If the after-beat restart flakes, the pytest output in beat 6 already
  proved the change — narrate and move on.

## Reset between rehearsals

`./demo/reset_s3_springdemo.sh` then `./demo/reset_s3.sh`. Browser
localStorage clears itself via the reset marker.
