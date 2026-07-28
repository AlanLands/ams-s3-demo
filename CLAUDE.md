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
