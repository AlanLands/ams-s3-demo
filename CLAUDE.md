# AMS S3 Demo — Project Context

## What this is

Standalone build of **S3 (Enhancement)** only, split out from the original six-scenario
`sixFold` AMS demo repo (`/Users/alanlands/Documents/sixFold`) on 2026-07-23. The other
five scenarios (S1, S2, S4, S5, S6) are being built elsewhere by the team per the design
shown in a separate walkthrough video — not part of this project.

Code was copied over from `sixFold` as of that date and trimmed to just what S3 needs
(see Layout below). All five other scenario packages (`s1_triage/`, `s2_problem/`,
`s4_knowledge/`, `s5_predictive/`, `s6_dashboard/`) and `datagen/` were removed along
with their routers, frontend pages, tests, and scenario-specific tooling; the Streamlit
fallback console (`demo/unified_app.py`) went with them. The only thing salvaged from
S1 was the shared login roster, which now lives in `common/roster.py`.

## S3 Enhancement — scope

Small CR on the "MapleSure Insurance" demo app (add a policy/claim capability):
AI analysis → codegen → tests → docs → release notes.

## Layout — things `ls` won't tell you

- `repos/` holds the target repositories S3 operates *on*, one directory per
  repo — this is the drop folder. A repo directory carrying a
  `.s3targets.json` manifest registers itself at import via
  `s3_enhancement/discovery.py`; no edit to `targets.py` is needed. CRs go in
  the top-level `crs/` and are picked up on the board automatically, landing
  unassigned so the manager routes them. See `repos/README.md` for the
  manifest contract and what a dropped-in repo does and does not get.
  The three built-in targets stay declared by hand in `targets.py` because
  they carry bespoke codegen file-set validators a manifest cannot express;
  built-ins win on an id clash, but two dropped repos colliding still raises.
- `apps/` holds the *tooling* — the console and the launch scripts (see
  `apps/README.md`). The distinction is load-bearing: a repo under `repos/` is
  something S3 changes; an app under `apps/` is what does the changing.
  Everything else at the root is also tooling: `s3_enhancement/` is the AI
  pipeline, `common/` the shared clients, `demo/` the presenter scripts.
- `repos/policycore/` (was `mockapp/`) is the MapleSure portal AND S3's first
  target — CR-2026-041 and CR-2026-042. Its Python package moved with it, so
  imports are `repos.policycore.core.*`.
- `repos/claimsportal/` is S3's second target — "ClaimsPortal"
  (Python/FastAPI, CR-2026-043, ticket AMS-103, target id
  `claimsportal-claims-deductible`). Runs on nothing but the venv, so a
  locked-down sandbox can host it. Its `target_id` and `cache_namespace` were
  renamed off their original "spring"/"springdemo" literals on 2026-07-31:
  `target_id` is not internal — `scm.branch_name_for` folds it into the
  branch shown at Step 0, so the stale name was on screen. `cache_namespace`
  *is* the committed recording's filename
  (`s3_{beat}__{cache_namespace}.json`), so both recordings were renamed in
  the same commit; renaming one without the other is a replay miss that
  silently falls through to a live call. It is one
  folder holding two services because CR-2026-043 edits files in both, so S3
  treats it as a single target root; they still start as two processes.
  Checked-in source is the pre-CR baseline (snapshot in `.baseline/`); reset
  with `demo/reset_s3_claimsportal.sh`. Its generated test and regression suite
  now live in the top-level `tests/` dir like the other two targets (the
  Java-only exception for in-target-root test discovery no longer applies).
- `repos/enroldirect/` is S3's third target — "EnrolDirect"
  (Python/FastAPI, CR-2026-045, target id `enroldirect-prospect-access`,
  cache namespace `enroldirect_prospect_access`). The online enrolment
  channel: two access preferences own who may self-serve, and a third
  population — prospects, on the roster with no active benefit — that
  neither preference was written for.
  **Its baseline is a removal, which is what makes it different from the
  other two.** The checked-in source is the state after the impact analysis
  and before the gate acts on it: `eligibility.preference_for_category`
  returns `None` for a prospect, so they are refused. The CR settles the
  classification. `impact.py` is in `core_files` but deliberately NOT in
  `codegen_allowlist` — the model must read the analysis to understand the
  change and must not edit it, which is why this target has its own
  `_validate_enroldirect_file_set` (core recall over the editable core files
  only, plus a loud failure if a read-only file comes back modified).
  Baseline snapshot in `.baseline/`; reset with
  `demo/reset_s3_enroldirect.sh`.
- `apps/console/` is the console: `api/` (FastAPI, run as
  `uvicorn apps.console.api.main:app`) and `web/` (React, was `frontend/`).
- `s3_enhancement/cache/` is the committed replay cache that makes the demo
  deterministic; `s3_enhancement/out/` is gitignored and regenerated per run.
- `tests/` holds both the pipeline's own tests **and** the target apps'
  checked-in regression suites (`test_regression_policycore.py`,
  `test_regression_claimsportal.py`, `test_regression_enroldirect.py`). The
  regression suites are deliberately
  outside every target root: anything ending `.py` under a target root joins
  the codegen candidate pool (see below). Until the 2026-07-30 Python rewrite,
  ClaimsPortal's Java regression suite was the one exception, living at
  `repos/claimsportal/policy-service/src/test/` — safe only because
  `relevance.py` excludes `test`/`tests` directories from discovery. That
  exclusion stays in `relevance.py` (harmless, still guards decoy test dirs)
  but no target now depends on it — all three keep their regression suite and
  generated-test output in `tests/`.
- The demo reset scripts restore from `HEAD`, **not** from the `s3-baseline` /
  `s3-endorsement-baseline` tags. Those tags predate both this layout and the
  amendments table, and restoring from them breaks reseeding with a FOREIGN
  KEY error that cannot be recovered without deleting `data/mockapp.db`.

## PolicyCore speaks GRS, not P&C (2026-08-03 reskin)

The demo audience is Group Retirement Services / group benefits, so PolicyCore's
vocabulary was reskinned off P&C wording: **endorsement → amendment**
(`core/endorsements.py` → `core/amendments.py`, `Endorsement` → `Amendment`,
`endorsements` table → `amendments`), **coverage tier / coverage level → plan
tier** (`coverage_tier` → `plan_tier`, `core/coverage.py` → `core/tiers.py`,
`COVERAGE_TIERS`/`upgrade_coverage` → `PLAN_TIERS`/`upgrade_tier`), **premium →
contribution** (`premium` → `contribution`), and **policyholder → plan sponsor**
(`holder_name` → `sponsor_name`). Tier names (Standard/Premium/Plus) are
generic and unchanged, as are `plan member`, `group contract`, `dependant`,
`roster` and `effective date` — those were already correct.

Plain "coverage" meaning *what a benefit covers* (`enrolment/dependants.py`,
marketing copy) is correct group-benefits English and was deliberately left
alone. ClaimsPortal and EnrolDirect were out of scope.

Three things kept their pre-reskin spelling on purpose, because they are cache
identity rather than display strings: `DEFAULT_TARGET_ID`
(`mockapp-coverage-upgrade`), `AMENDMENT_TARGET_ID`
(`mockapp-endorsement-field-add`) and `cache_namespace`
(`endorsement_field_add`), plus the `_LEGACY_CACHE_KEYS` literals. See the
comment above `DEFAULT_TARGET_ID` in `s3_enhancement/targets.py`.

`db.wipe_db()` drops the legacy `endorsements` table first and unconditionally.
That is not dead code: a `data/mockapp.db` created before the reskin still has
it, it references `policies`, and one row left in it makes the `policies` drop
fail with `FOREIGN KEY constraint failed` — the unrecoverable reseed this file
warns about above.

## File paths are load-bearing — don't move targets

`s3_enhancement/relevance.py::_document()` folds each file's path into the text
it scores (`f"{rel_path} {content}"`) — deliberately, since the path carries
subsystem/filename signal that content alone loses across ~100 similarly-shaped
decoy files. So a target's directory path is a *scoring input*.

Renaming or moving a target directory changes every embedding, reshuffles which
files the relevance funnel selects, and desyncs that selection from the
committed codegen recordings in `s3_enhancement/cache/`. The beat then dies with
`LLMError: codegen returned unexpected file set` — in replay mode, offline, with
no live fallback. Verified against the ClaimsPortal target on 2026-07-26.

Moving a target is a path-rewrite across code *and* the committed recordings,
not a `mv`. Done once, on 2026-07-28, for the `apps/` restructure: the
recordings carry these paths both as file keys and inside the generated code's
own `import` statements, so both had to be rewritten together, and both
targets were re-verified generate → apply → revert afterwards. A live
re-record was NOT needed. If you move one again, expect the same two-part
rewrite plus a fresh end-to-end pass.

Done a second time on 2026-08-03, moving all three targets from `apps/` into
the new `repos/` drop folder: 128 files rewritten across code, docs and the
committed recordings together, and again **no live re-record was needed** —
all four targets replayed, their mutation snippets still matched, and the
regression suites passed pre- and post-CR. Two traps that pass a `grep` but
break at run time: paths built as split literals (`REPO_ROOT / "apps" /
"policycore"`) are invisible to an `apps/policycore` search, and files with
unusual extensions (`.env.example`, `deploy/aws/*.service`) fall out of an
extension allowlist. Both bit on the first pass. Verify with
`s3_enhancement/discovery.py`-aware end-to-end run, not with grep alone.

## Release artifacts

`s3_enhancement/release.py` holds the deployment plan and the release record.
The plan is **derived** — deploy order comes from the change map's service
graph (callee before caller), the migration step from the target's
`post_apply_command`, verification from its regression suite. No LLM.

The release record is an assembly of what the run produced, and its
"Not evidenced by this release" block is load-bearing: a release document
that only lists successes is marketing. `unproven_claims()` is what keeps it
honest — extend that when you add evidence, not just the happy path.

Approvals in the record come from `common/ticket_events.py` server-side, never
from the client posting them. `POST /s3/release/attach` really uploads only
when `JIRA_MODE` is not `replay`; under the demo default it records the intent
and reports `simulated: true`. Don't "fix" that into a fake success.

Release notes are now three audience-specific fields (`draft_release_note_set`,
cache beat `release_note_set`). The older single-blob `draft_release_notes`
still exists for the legacy `/release-notes` endpoint and the rehearsal
scripts — the two must keep separate cache keys, or replay hands JSON to a
caller expecting prose.

## The source-control flow is modelled and must stay that way

`s3_enhancement/scm.py` frames Apply with branch → commit → push, because
applying straight to the working tree skips the part every reviewer asks about
(you do not edit main). **Nothing in it runs git** — no subprocess, no remote,
`simulated=True` on every response, and `git_transcript()` renders the commands
a real integration *would* have issued.

That is a constraint, not an unfinished feature. The target apps live inside
this repo and `demo/reset_s3*.sh` restore their baseline with `git checkout
HEAD -- <paths>`; a real commit would put the CR into HEAD, so the resets would
start silently restoring the change instead of the baseline. That failure
surfaces mid-rehearsal, not at the call site.
`tests/test_s3_scm.py` asserts the guarantee structurally on the parsed AST
(imports and call names, not substrings — the module's own prose and transcript
legitimately contain the words "commit" and "push"), the same way
`tests/test_autofix_no_git_writes.py` does for the autofix loop. A real SCM
integration belongs in a new module behind an explicit mode flag; do not turn
`simulated` into a lie in this one.

Two things carry the honesty: the panel's banner (`ScmPanel.tsx`) and
`release._source_control_gaps()`, which puts the un-run pipeline in the release
record's "Not evidenced by this release" block. Every branch state has a gap
line — no branch, applied-but-uncommitted, committed-but-unpushed, abandoned,
and pushed-but-simulated — so a modelled push can never read as a deployment
that happened.

The commit gate reads `tests_passed`/`tests_failed` and
`regression_passed`/`regression_failed` off the ticket's event log
**server-side** (`scm.commit_blockers`), never from a flag the console posts —
same rule as the release record's approvals. A client that could assert "tests
passed" could commit a red branch, which would make the beat's central claim
false. It reads the *latest* run of each suite, not any run, so a fixed suite
unblocks and a newly-broken one re-blocks.

State lives at `s3_enhancement/out/{proposal_id}/scm.json`, keyed by proposal
like staged files, backups, and rejections — so `demo/reset_s3.sh`'s
`rm -rf s3_enhancement/out/*` already clears it.

## Two things in the QA hand-off are deliberately not AI output

`s3_enhancement/diagram.py` (the design doc's change map) and
`s3_enhancement/acceptance.py` (the traceability matrix's criteria column) are
both pure functions of data already on hand — the changed-file set and the CR
text. No LLM call, so no cache key, no warming, and nothing to go wrong on a
cache miss. Keep it that way: the moment either becomes model output it needs
a replay recording and can be confidently wrong on stage. The diagram's
provenance caption (`diagram.caption_for`) exists to say so in the document,
and only claims the parts a given diagram actually contains.

PDF export renders server-side through Playwright's chromium
(`s3_enhancement/designdoc.py`). Chromium is an optional runtime dependency:
missing browser → `PdfUnavailableError` → HTTP 503 → the console falls back to
browser print. Do not turn that 503 into a 500.

## The regression suites are the AI's blind spot on purpose

`Target.regression_paths` / `regression_command` name a checked-in,
human-authored suite per target. Nothing in the pipeline may write to those
paths — `tests/test_s3_testrun.py` asserts they never appear in a
`testgen_allowlist` or `codegen_allowlist`, and that assertion is the whole
value of the beat. If you ever need S3 to generate into one of them, you have
removed the only independent check that a CR broke nothing.

Two rules for anything added to them: it must pass **before and after** every
CR (they are invariants, not assertions about the change under test), and it
must stay out of the target roots for the corpus reason above. Both suites
were verified pre-CR, post-CR, and against three injected breakages on
2026-07-29.

## Hard rules — carried over, still non-negotiable

1. **No real client data, ever.** All data must be synthetic (generated) or from public
   datasets. If a file looks like a real client export, stop and flag it — do not
   process it.
2. **No client names in code, data, commits, or UI.** The demo insurer is the fictional
   **"MapleSure Insurance"**. Refer to the end client only as "the client" in docs.
3. **API keys live in `.env` (gitignored), read via environment variables.** Never
   hardcode, print, or commit a key.
4. **Must survive a port to a locked-down environment.** Plain Python + CSV/SQLite +
   static/simple web UI preferred. No cloud-managed services, no Docker-required paths,
   no OS-specific hacks. Pin dependencies.

## Open / TBD

- Demo date and presentation format — TBD (see project owner for latest).
- The directory-naming problem is resolved: the four applications moved under
  `apps/` on 2026-07-28 (see Layout above). No re-record was required.
- `deploy/aws/` lost three uncommitted files on 2026-07-28 —
  `ams-s3-claims.service`, `ams-s3-policy.service`, `rebuild-spring.sh`. They
  were never committed, so they are unrecoverable; the systemd units still in
  the folder also predate the `apps/` restructure and will need their paths
  updated before the next EC2 deploy.
