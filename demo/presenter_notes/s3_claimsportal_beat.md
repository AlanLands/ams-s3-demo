# S3 — ClaimsPortal beat (second target, ~8 min)

**Point being made**: S3 is a pipeline, not a party trick tuned to one app.
Same console, same beats, a second independently-registered repo/target,
second user story. (There is now a third — EnrolDirect, US-2026-045 — if anyone asks
whether two is a coincidence.) (Until 2026-07-30 this beat also carried a second-language story —
ClaimsPortal is Python/FastAPI, verified via pytest. It was
rebuilt in Python/FastAPI so the demo runs without a JVM/Maven; the pipeline
now speaks pytest end to end across all three scenarios. What this beat
proves today is a second real repo the pipeline generalizes to, not a second
tech stack.)

**Cast**: `repos/claimsportal` = "ClaimsPortal". policy_service (:8081,
"MapleSure — Group Contracts", the Contracts Team console) serves policies;
claims_service (:8082, "MapleSure — Benefit Claims", the Claims Team console)
validates each submitted claim by calling policy_service over REST.
**US-2026-043 — Benefit Claim Deductible Handling** (`stories/US-2026-043.md`,
Jira AMS-103, assignee Ravi Kumar)
adds a per-policy deductible: below-deductible claims are rejected, accepted
claims record a payable amount. Fixed contract: `claim_rules.decide`/`payable`
module-level functions.

> **Vocabulary — ClaimsPortal is the exception.** The 2026-08-03 GRS reskin
> renamed PolicyCore's P&C wording (endorsement → amendment, coverage tier →
> plan tier, premium → contribution, policyholder → plan sponsor).
> ClaimsPortal deliberately **keeps** claim, deductible and annual maximum —
> that is correct group-benefits health/dental/disability English. Its API
> contract (`policyNumber`, `holderName`, `decide`, `payable`,
> `REJECTED_BELOW_DEDUCTIBLE`) is frozen too: renaming any of it desyncs the
> committed replay recording. Do not "correct" this on stage.

> **Artifacts open in a pop-up.** The design doc, the test checklist, the
> release notes and the traceability matrix no longer render down the page —
> each stage shows a button, a one-line verdict, a summary chip and a
> **View…** button that opens the body in a modal. Do not say "scroll down".

## Pre-flight (before the audience is in the room)

```bash
./demo/reset_s3_claimsportal.sh   # ClaimsPortal back to pre-user story baseline
./demo/reset_s3.sh                # shared state: out/, ticket events, .cache/llm
uvicorn apps.console.api.main:app --port 8000  # terminal 1 — API :8000 (never --reload:
                                  # Generate/Apply write .py files, the watcher
                                  # restarts, and your login session 401s)
(cd apps/console/web && npm run dev)    # terminal 2 — console :5173
./demo/run_s3_claimsportal.sh     # terminal 3 — both team consoles :8081/:8082
```

> Both resets work. `reset_s3.sh` is only here for the shared state this beat
> wants cleared (`out/`, ticket events, `.cache/llm`) — but it restores
> PolicyCore first with `git checkout HEAD -- repos/policycore/...`, so if a
> target has just been moved without committing the move, it dies on `error:
> pathspec ... did not match any file(s) known to git` and never reaches the
> cleanup. Committing the move is the fix.
> `reset_s3_claimsportal.sh` restores by `cp` from
> `repos/claimsportal/.baseline/` and never touches git, so it is immune to
> that. If you ever need the shared state cleared without the PolicyCore
> restore, the `/admin` panel's proposals / caches / tickets scopes are
> delete-only and never blocked.

Check: :8081 policies show **no Deductible**; claims console accepts an
80-dollar claim on MS-1004 (this exact claim gets rejected later — the
before/after moment). Make sure no stale service holds 8081/8082
(`pkill -f 'policy_service|claims_service'` first if in doubt) — a stale
process serves the OLD behavior and silently ruins the after-beat.

## Beats

1. **Before**: Contracts Team console (:8081) and Claims Team console (:8082).
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
   To Do → In Progress automatically. After Apply, draft the design doc and
   press **View design doc**: it opens in a pop-up as an actual MapleSure
   letterhead document, downloadable as .html/.md/.pdf ("this is the artifact
   QA receives"). Then hand off: pick a
   tester (Priya Nair, passcode 1003, or Tom Becker, 1004) → the card moves
   to the **QA column**, assigned to them, and the developer is now locked
   out of the test step (show the lock hint).
6. **Generate tests, as the tester**: log out, log in as the tester, open
   the ticket from the QA column, run "Generate tests + run": a pytest suite
   (`tests/test_s3_claims_deductible.py`) — same runner as the other
   scenarios. All green. The checklist and the run output each open in their
   own pop-up.
7. **After**: restart the services (Ctrl-C terminal 3, rerun
   `./demo/run_s3_claimsportal.sh`), resubmit the
   same 80-dollar claim on MS-1004 → **REJECTED_BELOW_DEDUCTIBLE**; a
   1,200-dollar claim on MS-1001 → ACCEPTED with **payableAmount 700**.
8. **Release notes** (still as the tester) — press **View** to open them;
   three audience-specific notes (client, ops, user guide), not one blob.
   Then "QA passed — mark ticket Done" closes the loop on the board.

## Fallbacks

- All generative beats replay from committed recordings
  (`s3_enhancement/cache/*claimsportal_claims_deductible*`, plus `.cache/llm` once
  warmed) — with `LLM_MODE=replay` (the default) the whole flow runs offline.
  `reset_s3.sh` wipes `.cache/llm`, so either re-warm the narrative beats in
  rehearsal or skip that wipe on demo day.
- If the after-beat restart flakes, the pytest output in beat 6 already
  proved the change — narrate and move on.

## Reset between rehearsals

`./demo/reset_s3_claimsportal.sh` then `./demo/reset_s3.sh`. Browser
localStorage clears itself via the reset marker.

The first works. The second does not, until the `repos/` move is committed —
see the pre-flight warning above. While it is broken it also never writes the
reset marker, so **the console's localStorage is not cleared either** and a
stale per-ticket analysis can survive into the next rehearsal. Hard-refresh
the console, or use the `/admin` panel's tickets/proposals/caches scopes,
which are delete-only and always available.
