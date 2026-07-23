# Demo run/reset scripts

One `run_sX.sh` + `reset_sX.sh` pair per scenario, so any rehearsal can start from a
known-good state and any beat can be re-run in isolation.

## Convention

- `run_sX.sh` — launches that scenario's live-demo surface (a Streamlit app, or for
  S5 a CLI narrative — see below). Zero-argument defaults are safe for the live demo;
  some accept args/env vars for rehearsal (`PORT` for Streamlit port).
- `reset_sX.sh` — restores pristine state for that scenario: reseeds any
  scenario-owned DB, regenerates any scenario-owned generated file, clears the shared
  LLM cache (`.cache/llm` — shared across all scenarios today; wiping it resets
  everyone's cache, not just one scenario's. Revisit with a scenario-scoped
  `cache_key` prefix if that becomes a problem before the demo.).
- Every script `cd`s to the repo root itself and activates `.venv` before running
  anything.
- `run_unified.sh` — the exception to "one scenario per script": launches
  `demo/unified_app.py`, which hosts all six scenarios together behind a
  sidebar scenario selector, in one Streamlit process on one port, so a
  presenter can run the whole demo without switching browser tabs or terminal
  windows. It reuses each scenario's existing `app.py` unchanged (imports and
  calls each one's `render()`) rather than duplicating any pipeline/view
  code — see the module docstring in `demo/unified_app.py` for why a sidebar
  radio was used instead of `st.tabs`. There is no `reset_unified.sh`; run the
  individual `reset_sX.sh` scripts for the scenarios you need reset, same as
  when rehearsing standalone.
- `run_s3_harness.sh` is a second, additive entry point for S3 only: the
  codegen/testgen "money shot" beat can optionally run through a live
  headless coding-agent CLI (Claude Code or Codex CLI) in a visible terminal
  instead of the Streamlit-driven `codegen.py`/`testgen.py` pipeline — see
  "S3 live agent-harness beat" below. `run_s3.sh` and `reset_s3.sh` are
  unchanged and remain the primary/fallback path.
- S5 is the one scenario whose originally-scoped surface (`SCENARIOS.md`) is
  CLI-only. `s5_predictive/app.py` adds a read-only Streamlit view (log scan
  report, predictive alert, and the self-heal approval gate) purely so S5 has
  a page inside `unified_app.py` alongside the other five — `run_s5.sh`'s CLI
  narrative remains the canonical, scripted demo entry point for S5 itself.
- Every scenario view shares one visual theme (`.streamlit/config.toml` +
  `common/ui_theme.py`) so standalone and combined launches look like one
  product, not six differently-styled prototypes.

## Status

| Scenario | run script | reset script | surface |
|---|---|---|---|
| S1 Incident Triage | `run_s1.sh` | `reset_s1.sh` | Streamlit (`s1_triage/app.py`) — auto-draft + chatbot modes |
| S2 Problem & RCA | `run_s2.sh` | `reset_s2.sh` | Streamlit (`s2_problem/app.py`) |
| S3 Enhancement | `run_s3.sh` | `reset_s3.sh` | Streamlit (`mockapp/app.py`) — coverage-upgrade capability |
| S4 Knowledge | `run_s4.sh` | `reset_s4.sh` | Streamlit (`s4_knowledge/app.py`) |
| S5 Predictive Ops | `run_s5.sh` | `reset_s5.sh` | CLI (canonical, per SCENARIOS.md) — detection + self-heal narrative. `s5_predictive/app.py` adds a read-only Streamlit view for the unified nav only |
| S6 Governance | `run_s6.sh` | `reset_s6.sh` | Streamlit (`s6_dashboard/app.py`) |
| S1-S6 combined | `run_unified.sh` | *(none — reset the individual scenarios)* | Streamlit (`demo/unified_app.py`) — sidebar-selected S1-S6, one port (default 8512) |

Dev-only smoke tools (not the live-demo entry points, kept for quick verification
without a browser or LLM key):
- `smoke_s1_pipeline.sh [row_index]` — CLI print of the full S1 pipeline for one row
- `run_s1_quality_gate.sh [row_index]` — CLI print of just the S1 data-quality gate

### S1 quality-gate smoke test (once an API key is in `.env`)

```bash
demo/run_s1_quality_gate.sh 42   # junk incident ("app not working") -> expect REJECTED + drafted mail
demo/run_s1_quality_gate.sh 57   # normal incident (partner feed ack delayed) -> expect INVESTIGABLE
demo/run_s1_quality_gate.sh 42   # rerun -> should hit cache, no live API call
```

These row indices are stable for `--seed 42` (the SEEDS.md default).

### S1 cache warm-up (run right before presenting)

`reset_s1.sh` wipes `.cache/llm` on purpose, so the next click after a reset pays
full LLM latency. `warm_s1_cache.sh` pre-populates the cache for the scripted demo
rows by calling the same pipeline functions the My Queue background pass does
(including its early stop for a rejected incident), so nothing is warmed that
the demo won't actually use:

```bash
demo/reset_s1.sh
demo/warm_s1_cache.sh        # warms rows 42 and 57 (the scripted rows)
demo/warm_s1_cache.sh 42 57 103   # or pass explicit row indices to warm more
```

After this, `demo/run_s1.sh` should serve both scripted rows from cache instantly —
no live call, no latency, no provider-outage risk on stage.

### S2 / S3 cache warm-up (same pattern, run right before presenting)

```bash
demo/reset_s2.sh
demo/warm_s2_cache.sh   # warms the 3 scripted clusters (memory leak, SSO, uploads)

demo/reset_s3.sh
demo/warm_s3_cache.sh   # warms the 2 fixed-key drafts (impact analysis, release notes)
```

Note `.cache/llm` is shared across all scenarios (see Convention above) — resetting
any one scenario wipes every other scenario's warmed cache too. Re-run all three
warm scripts (`warm_s1_cache.sh`, `warm_s2_cache.sh`, `warm_s3_cache.sh`) as the last
step before presenting, regardless of which reset script ran last.

### S3 live agent-harness beat (`s3_enhancement/harness.py`, `run_s3_harness.sh`)

Rung 1 of a 3-rung fallback ladder for S3's codegen+test beat: a real headless
coding-agent CLI (`claude -p` or `codex exec`, per `AGENT_HARNESS`) edits
mockapp itself and runs pytest itself, in a second terminal pane the
presenter opens before the demo starts. `mockapp/CLAUDE.md`/`AGENTS.md` pin
the exact file scope and API contract (mirrored from `codegen.py`'s prompt)
as the determinism lever. `codegen.py`/`testgen.py` are untouched and remain
rung 3, reachable via the existing Streamlit buttons with zero new code.

```bash
demo/reset_s3.sh
demo/run_s3.sh                     # Streamlit console, beats 1-2 (impact analysis, effort estimate)
demo/run_s3_harness.sh Elite       # second terminal pane, rung 1: live harness run
demo/run_s3_harness.sh --replay Elite   # rung 2: replay a rehearsed recording instead
```

After a harness run, click "Load latest harness run" in the Streamlit console
to review the diff (labeled `AI suggestion — verify with your specialist
before applying.`) and confirm it before the release-notes button unlocks —
the human-in-the-loop gate for a beat that (unlike `codegen.py`'s
stage-before-apply pattern) edits the working tree directly.

Record a rehearsal for the rung-2 fallback (do this well before demo day, not
live):

```bash
demo/reset_s3.sh
HARNESS_MODE=record demo/run_s3_harness.sh Elite
```

This templates the audience-picked tier name out to the literal `{{TIER_NAME}}`
token in the recording — same idiom as `common/llm.py`'s stream replay cache —
so `--replay` reproduces it for whatever name the audience actually picks on
the day, not just "Elite".

Rehearse `AGENT_HARNESS=claude` and `AGENT_HARNESS=codex` and pick whichever
lands the change more reliably; both must be pre-authenticated/trusted for
this exact repo directory on the presenter machine before demo day —
first-run auth/trust prompts will break headless mode otherwise.

### Automated live verification (`tools/verify_common.py`, `tools/autofix/`)

Manually spot-checking a live LLM call once is not enough to trust a fix — S1's
quality gate flipped pass/fail on identical input across repeated live calls near its
calibration boundary (see the 2026-07-16 entry below), which a single check would
have missed entirely. `tools/verify_s1_live.py`, `tools/verify_s2_live.py`, and
`tools/verify_s3_live.py` share a `tools/verify_common.py` harness with a
`run_multi_trial_check` primitive: every calibration-sensitive check runs 5x live
(`LLM_NO_CACHE=1`) and only passes if all 5 do.

```bash
python -m tools.verify_s1_live   # row 15/0 + all 6 background templates, 5x each
python -m tools.verify_s2_live   # cluster discovery, RCA/fix grounding, cache-hit-on-rerun
python -m tools.verify_s3_live   # impact analysis / release notes structural checks
```

`tools/autofix/` goes one step further: an unattended detect → propose → apply →
safety-gate → re-verify → accept/revert loop that can fix a failing calibration check
without a human in the loop mid-run (see `tools/autofix/loop.py`'s module docstring
for the full design — bounded iterations, a narrow AST-located editable surface, a
zero-LLM-cost safety gate on every accepted change, and a full audit trail under
`.cache/autofix_runs/<run_id>/`). Nothing here ever commits or pushes (structurally
enforced by `tests/test_autofix_no_git_writes.py`) — review `summary.md` and
`diff.patch` in the run directory before committing anything it changes.

```bash
python -m tools.autofix.loop --scenario s1 --dry-run   # detect + propose only, no writes
python -m tools.autofix.loop --scenario s1             # live, will edit files if a check fails
python -m tools.autofix.loop --scenario s2              # no fix targets registered yet — surfaces failures for a human
python -m tools.autofix.loop --scenario s3
```

### S5 demo flow

```bash
demo/run_s5.sh              # detection narrative, then self-heal plan (not executed — awaiting approval)
demo/run_s5.sh --approve --approver "on-call-engineer"   # same, but executes the simulated restart
```

### Status of live-call verification

Every scenario's LLM-calling code is unit-tested with `common.llm.complete` mocked at
the call site (see `tests/`), and the deterministic/statistical logic (clustering,
similar-incidents, routing, log-window detection, dashboard metrics) is tested for
real, no mocking. `LLM_PROVIDER=openai` in `.env`.

**S1 — live-verified 2026-07-15** (CLI path only so far). First live run of
`demo/run_s1_quality_gate.sh` immediately failed on the flagship demo row and the
"clean" row — a real calibration bug, not a code defect: the dataset's descriptions
maxed out at 177 characters and the gate's prompt demanded telemetry no requestor
would supply. Fixed in `s1_triage/prompts.py` and
`datagen/generate_incidents.py`'s description templates (see `datagen/SEEDS.md`).
Re-verified live across a stratified sample: 6/6 real incidents → investigable, 3/3
`junk_quality_gate` rows → still correctly rejected.

**S1 — recalibrated for GPT-5, 2026-07-16.** The above was verified against Claude
Sonnet only. `.env` now runs `LLM_PROVIDER=openai` (the actual leadership-steer
default), and a fresh live call against GPT-5 rejected row 57 — stricter grading,
plus genuine run-to-run non-determinism near the pass/fail boundary (confirmed by
re-testing unchanged templates 3x live and getting different verdicts). Fixed the
same way as before: loosened `s1_triage/prompts.py` further and added a touch more
business-level detail (an approximate clock time + an existing `CI_BY_APP` hostname)
to 4 of the 6 `BACKGROUND_TEMPLATES` entries — see `datagen/SEEDS.md` for the full
account and the multi-trial numbers. Re-verified all six templates 5/5 live, and
`demo/reset_s1.sh` → `demo/warm_s1_cache.sh` 3x fresh with row 57 landing
`investigable` every time. Full `demo/run_s1.sh` Streamlit pass (all beats, not just
CLI) confirmed working; cache-hit-on-rerun confirmed via `demo/warm_s1_cache.sh`
(second run touches no new cache files).

**S2 — live-verified 2026-07-16** via `tools/verify_s2_live.py` /
`tools/autofix/loop.py --scenario s2` (5x live against GPT-5, `LLM_NO_CACHE=1`).
Cluster A's RCA correctly cited `PRB0001234`/`KE0000456` and the restart/rerun
workaround language 5/5 — no fix needed, no files touched. `warm_s2_cache.sh` added
for demo-reliability parity with S1.

**S3 — live-verified 2026-07-16** via `tools/verify_s3_live.py` /
`tools/autofix/loop.py --scenario s3` (5x live against GPT-5 each,
`LLM_NO_CACHE=1`). Both the impact-analysis and release-notes drafts were
structurally sound (non-degenerate, no refusal pattern, release notes showed the two
distinct parts asked for) 5/5 — no fix needed, no files touched. `warm_s3_cache.sh`
added for demo-reliability parity with S1. Note: this checks structural soundness,
not narrative *quality* — grading quality would need another LLM call and would
reintroduce the same non-determinism this tooling exists to catch, so that's still a
human judgment call on a live run-through before the demo.

**S4–S6 — not yet live-verified.** Do one live run of each remaining `run_sX.sh` and
confirm the AI-generated text renders sensibly and reruns hit the cache before the
demo.

## 90-minute run order (BUILD_PLAN.md)

Intro (5) → S1 (12) → S2 (12) → S6 (10) → S3 (15) → S4 (12) → S5 (14) →
roadmap/environment/governance asks (7) → Q&A (3)
