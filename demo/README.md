# Demo run/reset scripts

Every rehearsal starts from a known-good state, and every beat can be re-run in
isolation. All scripts `cd` to the repo root themselves and activate `.venv`
before running anything.

For the full end-to-end walkthrough of the four CR scenarios, see
**`DEMO_TEST_GUIDE.md`**; for standing the whole thing up from a clean
checkout, `DEMO_STEPS.md`. This file covers the scripts and the tooling around
them.

> **Where things live.** `repos/` holds the target repositories S3 *changes* —
> PolicyCore, ClaimsPortal, EnrolDirect. `apps/` holds the tooling that *does*
> the changing: the console, and one launch script per running process. The
> five per-process launchers (`apps/run-console.sh`, `run-policycore.sh`,
> `run-policy-service.sh`, `run-claims-service.sh`, `run-enroldirect.sh`) are
> documented in `apps/README.md` — the scripts below are the presenter's
> reset/seed/warm tooling, not the launchers.

---

## All four reset scripts work

Verified 2026-08-03: all four run to their success line and leave the working
tree matching `HEAD` exactly.

The one durable thing to know about them: `demo/reset_s3.sh` and
`demo/reset_s3_endorsement.sh` restore PolicyCore with `git checkout HEAD --
repos/policycore/...`, so **they can only restore paths that HEAD already
has**. Move a target directory and both scripts fail (`error: pathspec ... did
not match any file(s) known to git`) until the move is committed. That is the
whole fix when it happens — nothing in the scripts needs changing. It bit on
2026-08-03 while the `apps/` → `repos/` move was still uncommitted, and
committing the move (`e5af8ed`) resolved it.

Check it read-only any time you suspect it:

```bash
git cat-file -e HEAD:repos/policycore/app.py 2>/dev/null && echo "in HEAD" || echo "NOT in HEAD"
```

Two things worth carrying forward:

- **ClaimsPortal and EnrolDirect resets never depend on git.**
  `reset_s3_claimsportal.sh` and `reset_s3_enroldirect.sh` restore by `cp` from
  the in-repo `.baseline/` snapshots, so a target move cannot break them.
- The admin panel checks for the condition rather than discovering it halfway.
  `GET /api/admin/status` returns a `reset_blocked_reason` naming any paths
  missing from HEAD, and disables the PolicyCore reset button with that reason
  on it. That check is deliberate and stays — it earns its keep the next time
  someone moves a target.

Confirm a reset with the baseline checks in `DEMO_TEST_GUIDE.md` section 0a
rather than assuming it worked.

---

## The scripts

| Script | What it does |
|---|---|
| `run_s3.sh` | Streamlit S3 console (the legacy view; the React console at `apps/console/web/` + `api/` is the primary surface). Defaults to `PORT=8501`, which collides with `run_mockapp.sh` — set `PORT` if you want both. |
| `run_mockapp.sh` | Serves `repos/policycore/app.py` on :8501/sl_policycore — the "client's app" window for the before/after proof. Same job as `apps/run-policycore.sh`. |
| `run_s3_claimsportal.sh` | Runs the two Python/FastAPI ClaimsPortal services (:8081 contracts, :8082 claims) |
| `run_s3_harness.sh` | The live agent-harness variant of the codegen beat — see below |
| `reset_s3.sh` | CR-2026-041 (PolicyCore plan tier) back to pre-CR baseline; also clears shared state. Restores from `HEAD` — see above. |
| `reset_s3_endorsement.sh` | CR-2026-042 (PolicyCore amendment Priority field) back to baseline, restored from `HEAD` (**not** from the `s3-endorsement-baseline` tag — see the comment in the script). |
| `reset_s3_claimsportal.sh` | CR-2026-043 (ClaimsPortal) back to baseline, from `repos/claimsportal/.baseline/` |
| `reset_s3_enroldirect.sh` | CR-2026-045 (EnrolDirect) back to baseline, from `repos/enroldirect/.baseline/` |
| `warm_s3_cache.sh` | Pre-warms `.cache/llm` for the narrative drafts before presenting |
| `seed_problem_record_ticket.sh` | Seeds the problem-record intake ticket (needs the API on :8000 already running) |
| `seed_s3_repo_selection_ticket.sh` | Puts AMS-104 (CR-2026-044, the ticket that names no target system) back on the board. Needs no server; run it *after* `reset_s3.sh`, which restores the committed Jira caches and would otherwise drop it. |

> `run_mockapp.sh` and `reset_s3_endorsement.sh` were previously named
> `run_s4_endorsement.sh` / `reset_s4_endorsement.sh`. The "s4" was a leftover
> from the six-scenario repo — both are S3 beats. Renamed 2026-07-26.
> `reset_s3_endorsement.sh` kept its filename through the 2026-08-03 GRS
> reskin — teammates invoke it by name — even though the CR it resets is now
> "CR-2026-042: Amendment Priority Field". Only its contents changed.

### No script for CR-2026-045's ticket

There is deliberately none. A `.md` dropped into the top-level `crs/` opens a
board ticket by itself — the key is derived from the CR id (`CR-2026-045` →
**AMS-1045**), and the ticket lands **unassigned** so the manager routes it.
`seed_s3_repo_selection_ticket.sh` is the older hand-seeding path and stays
only because AMS-104 needs a specific pre-set assignee to make its beat work.

`reset_s3.sh` wipes `.cache/llm` on purpose, so the next click after a reset
pays full LLM latency. Run `warm_s3_cache.sh` as the last step before
presenting:

```bash
demo/reset_s3.sh
demo/warm_s3_cache.sh   # warms the fixed-key drafts (impact analysis, release notes)
```

## The admin panel is the in-console equivalent (`/admin`, manager only)

Most of what these scripts do is also a button at `http://localhost:5173/admin`
— useful when you are already presenting and do not want to switch to a
terminal. It runs the same reset scripts and the same delete logic, gated
server-side by `require_manager`.

Four cards: **Reset demo state**, **Target applications** (status + start/stop),
**Logs**, **Onboard a repo**.

Limits worth knowing before you rely on it live:

- Source-restoring scopes (`policycore`, `claimsportal`, `enroldirect`) **409
  while the tree is dirty**, and preview exactly what they would restore or
  delete and which files are currently dirty before you press anything.
- There is **no "reset everything"** scope. Each is explicit — PolicyCore,
  ClaimsPortal, EnrolDirect, tickets, logs, proposals, caches.
- **No service id for the console itself**, so it cannot restart the process
  serving your request.
- Service status is a plain TCP port probe — no `ps`, no `lsof` — so it works
  on a locked-down host, but "up" only means something is listening.
- A manifest written by **Onboard a repo** needs a console restart to take
  effect; discovery runs at import.

## S3 live agent-harness beat (`s3_enhancement/harness.py`, `run_s3_harness.sh`)

Rung 1 of a 3-rung fallback ladder for the codegen+test beat: a real headless
coding-agent CLI (`claude -p` or `codex exec`, per `AGENT_HARNESS`) edits
PolicyCore itself and runs pytest itself, in a second terminal pane the presenter
opens before the demo starts. `repos/policycore/CLAUDE.md` / `repos/policycore/AGENTS.md` pin the
exact file scope and API contract (mirrored from `codegen.py`'s prompt) as the
determinism lever. `codegen.py`/`testgen.py` are untouched and remain rung 3,
reachable via the existing console buttons with zero new code.

```bash
demo/reset_s3.sh
demo/run_s3_harness.sh Elite            # rung 1: live harness run
demo/run_s3_harness.sh --replay Elite   # rung 2: replay a rehearsed recording
```

After a harness run, click "Load latest harness run" in the console to review
the diff (labeled `AI suggestion — verify with your specialist before
applying.`) and confirm it before the release-notes button unlocks — the
human-in-the-loop gate for a beat that, unlike `codegen.py`'s
stage-before-apply pattern, edits the working tree directly.

Record a rehearsal for the rung-2 fallback well before demo day, not live:

```bash
demo/reset_s3.sh
HARNESS_MODE=record demo/run_s3_harness.sh Elite
```

This templates the audience-picked tier name out to the literal
`{{TIER_NAME}}` token in the recording — same idiom as `common/llm.py`'s stream
replay cache — so `--replay` reproduces it for whatever name the audience
actually picks, not just "Elite".

Rehearse both `AGENT_HARNESS=claude` and `AGENT_HARNESS=codex` and pick
whichever lands the change more reliably. Both must be pre-authenticated and
trusted for this exact repo directory on the presenter machine before demo day
— first-run auth/trust prompts will break headless mode otherwise.

## Automated verification (`tools/verify_s3_live.py`, `tools/autofix/`)

Manually spot-checking a live LLM call once is not enough to trust a fix:
calibration-sensitive checks can flip pass/fail on identical input across
repeated live calls. `tools/verify_s3_live.py` uses `tools/verify_common.py`'s
`run_multi_trial_check` primitive — every calibration-sensitive check runs 5x
live (`LLM_NO_CACHE=1`) and passes only if all 5 do.

```bash
python tools/verify_s3_live.py --skip-live   # 7 offline architecture checks, no API key
python tools/verify_s3_live.py               # the above plus the 5x-live narrative checks
```

The offline half is the pre-demo confidence gate: it proves replay works with
every provider path booby-trapped, that a mid-stream provider failure falls
back to replay invisibly, that one recording replays for any audience-chosen
tier name, that `reset_s3.sh` restores baseline in <10s, and that the relevance
funnel keeps core files while screening out the legacy decoys.

> That `reset_s3.sh` check is exactly what catches an uncommitted target move:
> the script cannot restore paths HEAD lacks, so the gate goes red. If it ever
> does, commit the move rather than editing the check — see the top of this
> file.

`tools/autofix/` goes further: an unattended detect → propose → apply →
safety-gate → re-verify → accept/revert loop that can fix a failing calibration
check without a human mid-run (see `tools/autofix/loop.py`'s module docstring —
bounded iterations, a narrow AST-located editable surface, a zero-LLM-cost
safety gate on every accepted change, and a full audit trail under
`.cache/autofix_runs/<run_id>/`). Nothing here ever commits or pushes
(structurally enforced by `tests/test_autofix_no_git_writes.py`) — review
`summary.md` and `diff.patch` in the run directory before committing anything
it changes.

```bash
python -m tools.autofix.loop --dry-run   # detect + propose only, no writes
python -m tools.autofix.loop             # live, will edit files if a check fails
```

`--scenario` accepts only `s3` in this repo.

## Status of live-call verification

Every LLM-calling path is unit-tested with `common.llm.complete` mocked at the
call site (see `tests/`); the deterministic logic (relevance funnel scoring,
target registry, test parsing) is tested for real, no mocking.

**S3 — live-verified 2026-07-16** via `tools/verify_s3_live.py` and
`tools/autofix/loop.py` (5x live each, `LLM_NO_CACHE=1`). Both the
impact-analysis and release-notes drafts were structurally sound
(non-degenerate, no refusal pattern, release notes showed the two distinct
parts asked for) 5/5 — no fix needed, no files touched.

Note this checks structural soundness, not narrative *quality*. Grading quality
would need another LLM call and would reintroduce the same non-determinism this
tooling exists to catch, so quality stays a human judgment call on a live
run-through before the demo.

**Offline gate — re-verified 2026-07-26.** All 7 architecture checks pass.
(The gate had been crashing before printing any result since the six-scenario
split; see commit `ba8136f`.) Re-run it after the `repos/` move is committed —
that verification predates both the move and the GRS reskin.
