# Demo run/reset scripts

Every rehearsal starts from a known-good state, and every beat can be re-run in
isolation. All scripts `cd` to the repo root themselves and activate `.venv`
before running anything.

For the full end-to-end walkthrough of the three CR scenarios, see
**`DEMO_TEST_GUIDE.md`** — this file covers the scripts and the tooling around
them.

## The scripts

| Script | What it does |
|---|---|
| `run_s3.sh` | Streamlit S3 console (the legacy view; the React console at `apps/console/web/` + `api/` is the primary surface) |
| `run_mockapp.sh` | Serves `apps/policycore/app.py` on :8501/sl_policycore — the "client's app" window for the before/after proof |
| `run_s3_springdemo.sh` | Runs the two Python/FastAPI ClaimsPortal services (:8081, :8082) |
| `run_s3_harness.sh` | The live agent-harness variant of the codegen beat — see below |
| `reset_s3.sh` | CR-2026-041 (mockapp coverage tier) back to pre-CR baseline; also clears shared state |
| `reset_s3_endorsement.sh` | CR-2026-042 (mockapp endorsement Priority field) back to baseline, via the `s3-endorsement-baseline` git tag |
| `reset_s3_springdemo.sh` | CR-2026-043 (ClaimsPortal) back to baseline, from `apps/claimsportal/.baseline/` |
| `warm_s3_cache.sh` | Pre-warms `.cache/llm` for the narrative drafts before presenting |
| `seed_problem_record_ticket.sh` | Seeds the problem-record intake ticket |

> `run_mockapp.sh` and `reset_s3_endorsement.sh` were previously named
> `run_s4_endorsement.sh` / `reset_s4_endorsement.sh`. The "s4" was a leftover
> from the six-scenario repo — both are S3 beats. Renamed 2026-07-26.

`reset_s3.sh` wipes `.cache/llm` on purpose, so the next click after a reset
pays full LLM latency. Run `warm_s3_cache.sh` as the last step before
presenting:

```bash
demo/reset_s3.sh
demo/warm_s3_cache.sh   # warms the fixed-key drafts (impact analysis, release notes)
```

## S3 live agent-harness beat (`s3_enhancement/harness.py`, `run_s3_harness.sh`)

Rung 1 of a 3-rung fallback ladder for the codegen+test beat: a real headless
coding-agent CLI (`claude -p` or `codex exec`, per `AGENT_HARNESS`) edits
mockapp itself and runs pytest itself, in a second terminal pane the presenter
opens before the demo starts. `apps/policycore/CLAUDE.md` / `apps/policycore/AGENTS.md` pin the
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
split; see commit `ba8136f`.)
