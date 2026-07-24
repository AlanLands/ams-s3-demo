# S3 — ClaimsPortal beat (Spring Boot second target, ~8 min)

**Point being made**: S3 is a pipeline, not a party trick tuned to one Python
app. Same console, same beats, second repo, second language (Java 21 / Spring
Boot 3, two Maven microservices), second CR — and the verification step runs
that stack's own toolchain (`mvn test` / JUnit 5), not pytest.

**Cast**: `sandbox/spring-demo` = "ClaimsPortal". policy-service (:8081, Policy
Team console) serves policies; claims-service (:8082, Claims Team console)
validates each submitted claim by calling policy-service over REST. CR-2026-043
(`sandbox/spring-demo/crs/CR-2026-043.md`, Jira AMS-103, assignee Ravi Kumar)
adds a per-policy deductible: below-deductible claims are rejected, accepted
claims record a payable amount. Fixed contract: `ClaimRules.decide/payable`.

## Pre-flight (before the audience is in the room)

```bash
./demo/reset_s3.sh              # shared state: out/, ticket events, .cache/llm
./demo/reset_s3_springdemo.sh   # ClaimsPortal back to pre-CR baseline
uvicorn api.main:app --reload   # terminal 1 — API :8000
(cd frontend && npm run dev)    # terminal 2 — console :5173
./demo/run_s3_springdemo.sh     # terminal 3 — both team consoles :8081/:8082
```

Check: :8081 policies show **no Deductible**; claims console accepts an
80-dollar claim on MS-1004 (this exact claim gets rejected later — the
before/after moment). Make sure no stale service holds 8081/8082
(`pkill -f 'policy-service|claims-service'` first if in doubt) — a stale
process serves the OLD behavior and silently ruins the after-beat.

## Beats

1. **Before**: Policy Team console (:8081) and Claims Team console (:8082).
   Submit an 80-dollar claim on MS-1004 → ACCEPTED. "Small claims below any
   deductible sail through to adjusters today."
2. **Console** (:5173, log in Ravi Kumar / 1001): open **AMS-103** on the
   board. This is a *Java* estate — the file-selection panel's
   per-language pool count shows it (8 Java files, 0 Python).
3. **Impact analysis + effort**: drafted against the real Java sources —
   names Policy.java / PolicyClient.PolicyView / a new ClaimRules class.
4. **Generate**: diff spans BOTH services — the record gains `deductible`
   on the policy side and the consuming record on the claims side, plus the
   new ClaimRules class. Point out reasons-per-file, then **Apply**.
5. **Design doc + QA hand-off**: the workflow is real Jira discipline, live
   on the board — running the analysis already moved the card
   To Do → In Progress automatically. After Apply, draft the design doc: it
   renders as an actual MapleSure letterhead document, downloadable as
   .html/.md ("this is the artifact QA receives"). Then hand off: pick a
   tester (Priya Nair, passcode 1003, or Tom Becker, 1004) → the card moves
   to the **QA column**, assigned to them, and the developer is now locked
   out of the test step (show the lock hint).
6. **Generate tests, as the tester**: log out, log in as the tester, open
   the ticket from the QA column, run "Generate tests + run": a JUnit 5
   suite (`ClaimRulesTest.java`), and the test run output is **Maven**, not
   pytest — the pipeline speaks the target repo's language end to end.
   5 tests green.
7. **After**: rebuild + restart the services (Ctrl-C terminal 3, rerun
   `./demo/run_s3_springdemo.sh` — it rebuilds automatically), resubmit the
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
- Maven needs a warm local repo: run `mvn -q package` once per service on the
  demo machine beforehand so demo-day builds are seconds, not downloads.
- If the after-beat restart flakes, the JUnit/Maven output in beat 5 already
  proved the change — narrate and move on.

## Reset between rehearsals

`./demo/reset_s3_springdemo.sh` then `./demo/reset_s3.sh`. Browser
localStorage clears itself via the reset marker.
