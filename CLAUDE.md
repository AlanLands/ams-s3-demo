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

- `apps/` holds the four *running* applications, one launch script each (see
  `apps/README.md`). Everything else at the root is tooling, not an app:
  `s3_enhancement/` is the AI pipeline, `common/` the shared clients, `demo/`
  the presenter scripts.
- `apps/policycore/` (was `mockapp/`) is the MapleSure portal AND S3's first
  target — CR-2026-041 and CR-2026-042. Its Python package moved with it, so
  imports are `apps.policycore.core.*`.
- `apps/claimsportal/` (was `sandbox/spring-demo/`) is S3's second target —
  "ClaimsPortal" (Java/Spring Boot, CR-2026-043, ticket AMS-103, target id
  `springdemo-claims-deductible`). It is one folder holding two services
  because CR-2026-043 edits files in both, so S3 treats it as a single target
  root; they still start as two processes. Checked-in source is the pre-CR
  baseline (snapshot in `.baseline/`); reset with `demo/reset_s3_springdemo.sh`.
- `apps/console/` is the console: `api/` (FastAPI, run as
  `uvicorn apps.console.api.main:app`) and `web/` (React, was `frontend/`).
- `s3_enhancement/cache/` is the committed replay cache that makes the demo
  deterministic; `s3_enhancement/out/` is gitignored and regenerated per run.
- `tests/` holds both the pipeline's own tests **and** the target apps'
  checked-in regression suite (`test_regression_policycore.py`). The
  regression suites are deliberately outside every target root: anything
  ending `.py`/`.java` under a target root joins the codegen candidate pool
  (see below). The Java one is the exception and lives at
  `apps/claimsportal/policy-service/src/test/` — safe only because
  `relevance.py` now excludes `test`/`tests` directories from discovery.
- The demo reset scripts restore from `HEAD`, **not** from the `s3-baseline` /
  `s3-endorsement-baseline` tags. Those tags predate both this layout and the
  endorsements table, and restoring from them breaks reseeding with a FOREIGN
  KEY error that cannot be recovered without deleting `data/mockapp.db`.

## File paths are load-bearing — don't move targets

`s3_enhancement/relevance.py::_document()` folds each file's path into the text
it scores (`f"{rel_path} {content}"`) — deliberately, since the path carries
subsystem/filename signal that content alone loses across ~100 similarly-shaped
decoy files. So a target's directory path is a *scoring input*.

Renaming or moving a target directory changes every embedding, reshuffles which
files the relevance funnel selects, and desyncs that selection from the
committed codegen recordings in `s3_enhancement/cache/`. The beat then dies with
`LLMError: codegen returned unexpected file set` — in replay mode, offline, with
no live fallback. Verified against the Spring target on 2026-07-26.

Moving a target is a path-rewrite across code *and* the committed recordings,
not a `mv`. Done once, on 2026-07-28, for the `apps/` restructure: the
recordings carry these paths both as file keys and inside the generated code's
own `import` statements, so both had to be rewritten together, and both
targets were re-verified generate → apply → revert afterwards. A live
re-record was NOT needed. If you move one again, expect the same two-part
rewrite plus a fresh end-to-end pass.

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
