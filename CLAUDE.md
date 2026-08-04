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

Small user story on the "MapleSure Insurance" demo app (add a policy/claim capability):
AI analysis → codegen → tests → docs → release notes.

## Layout — things `ls` won't tell you

- `repos/` holds the target repositories S3 operates *on*, one directory per
  repo — this is the drop folder. A repo directory carrying a
  `.s3targets.json` manifest registers itself at import via
  `s3_enhancement/discovery.py`; no edit to `targets.py` is needed. user stories go in
  the top-level `stories/` and are picked up on the board automatically, landing
  in the default engineer's **To Do** column — Ravi Kumar, per
  `s3.py::DEFAULT_STORY_ASSIGNEE`, overridable with `STORY_DEFAULT_ASSIGNEE`
  and set to unassigned by an empty value (which is what it did before
  2026-08-04). See `repos/README.md` for the
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
  target — US-2026-041 and US-2026-042. Its Python package moved with it, so
  imports are `repos.policycore.core.*`.
- **ClaimsPortal was removed on 2026-08-04** and is no longer a target. It was
  S3's second (US-2026-043, ticket AMS-103, target id
  `claimsportal-claims-deductible`, one folder holding two services). The repo,
  its story, its recordings, its regression and unit suites, its reset and run
  scripts and its `apps/run-*.sh` launchers all went with it. Its App Support
  group's members were merged into `App Support — PolicyCore` **appended in
  their original order at the position ClaimsPortal's group used to occupy** —
  passcodes are `1001 + position in the flattened roster`, so that placement is
  what keeps every presenter-note passcode pointing at the same person
  (`common/roster.py`). Historical references to it further down this file are
  dated and describe things that really happened; they are kept deliberately.
- `repos/enroldirect/` is S3's third target — "EnrolDirect"
  (Python/FastAPI, US-2026-045, target id `enroldirect-prospect-access`,
  cache namespace `enroldirect_prospect_access`). The online enrolment
  channel: two access preferences own who may self-serve, and a third
  population — prospects, on the roster with no active benefit — that
  neither preference was written for.
  **Its baseline is a removal, which is what makes it different from the
  other two.** The checked-in source is the state after the impact analysis
  and before the gate acts on it: `eligibility.preference_for_category`
  returns `None` for a prospect, so they are refused. The user story settles the
  classification. `impact.py` is in `core_files` but deliberately NOT in
  `codegen_allowlist` — the model must read the analysis to understand the
  change and must not edit it, which is why this target has its own
  `_validate_enroldirect_file_set` (core recall over the editable core files
  only, plus a loud failure if a read-only file comes back modified).
  Baseline snapshot in `.baseline/`; reset with
  `demo/reset_s3_enroldirect.sh`.
- `repos/documenthub/` is S3's fourth target — "DocumentHub"
  (Python/FastAPI, US-2026-046, target id
  `documenthub-rostered-guest-wording`, cache namespace
  `documenthub_rostered_guest_wording`, port 8084). The enrolment document
  service: it words a confirmation pack per *audience* and picks one.
  **It is the only target registered by a `.s3targets.json` manifest rather
  than declared by hand in `targets.py`**, and that is the point of it — the
  cross-team check on US-2026-045 names DocumentHub as the one other team
  owed work, and the repo was then dropped into `repos/` and became
  automatable with no edit to `targets.py`. It has **no committed codegen or
  testgen recording**: a discovered target has nothing to record against
  until its story runs once, so the first run is a live call that records
  itself (`repos/README.md`). Its declared mutation quotes
  `if record.onRoster:` from the *generated* `wording.py`, so re-verify that
  snippet against the recording after that first run — a stale snippet makes
  the mutation beat no-op silently.
  Its baseline is a **wrong document, not a failure**: `wording.audience_for`
  selects on the authorising preference alone, so the seeded record
  `ENR-20260804-005` (on the sponsor's roster, admitted under guest access —
  exactly what US-2026-045 starts producing) falls through to the guest pack
  and is told we hold no member record for them, with an identity form
  enclosed. Nothing raises and nothing logs. `feed.py` is in `core_files` but
  deliberately NOT in `codegen_allowlist` — it is EnrolDirect's integration
  contract, the same read-but-don't-edit arrangement as EnrolDirect's
  `impact.py` — and so is `main.py`, whose audit endpoint is the independent
  check on the selection rule. Baseline snapshot in `.baseline/`; reset with
  `demo/reset_s3_documenthub.sh`.
- `apps/console/` is the console: `api/` (FastAPI, run as
  `uvicorn apps.console.api.main:app`) and `web/` (React, was `frontend/`).
- `s3_enhancement/cache/` is the committed replay cache that makes the demo
  deterministic; `s3_enhancement/out/` is gitignored and regenerated per run.
- `tests/` holds both the pipeline's own tests **and** the target apps'
  checked-in regression suites (`test_regression_policycore.py`,
  `test_regression_enroldirect.py`, `test_regression_documenthub.py` — the
  ClaimsPortal one went with that target on 2026-08-04). The
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

## It is a "user story" everywhere — `CR` is gone, `crs/` is `stories/`

Renamed 2026-08-03, in full. The client's own intake artifact is a user story
(business objective, target population, Given/When/Then acceptance criteria),
so the vocabulary follows it end to end:

| Was | Is |
|---|---|
| `crs/` | `stories/` |
| `crs/CR-2026-045.md` | `stories/US-2026-045.md` |
| `CR-YYYY-NNN` id | `US-YYYY-NNN` |
| `s3_enhancement/cr_intake.py`, `cr.py` | `story_intake.py`, `story.py` |
| `cr_text` / `cr_id` / `cr_file` / `cr_label` | `story_text` / `story_id` / … |
| `/api/s3/cr`, `/api/s3/cr/file` | `/api/s3/story`, `/api/s3/story/file` |
| `.ams-cr-*` CSS | `.ams-story-*` |

The board opens these as issue type `Story`, and `story_intake.parse_story`
sets `summary=title` — no `US-2026-045:` prefix on the card.

**What did NOT change, and must not:** `target_id`, `cache_namespace`, and
therefore every recording filename in `s3_enhancement/cache/`. Ticket keys are
unchanged too (`US-2026-045` → `AMS-1045`), because `ticket_key_for` derives
them from the *number*, not the prefix. All eight codegen/testgen recordings
still resolve, verified.

Three traps this rename walked into — check them if you rename anything again:

- **Regex literals get mangled by a prose pass.** `re.compile(r"^(CR-\d{4}…")`
  became `^(user story-\d{4}…` and silently stopped matching, which dropped
  target resolution from the `story_id` tier to a live AI call. Same bug hit
  `scm._DISPLAY_NAME_TAIL`. After any bulk rename, grep your regex literals.
- **The seeded Jira recordings carry the id in their summaries.** The board
  search fetches only `summary, status, issuetype, assignee`
  (`common/jira_client.py`) — no description — so those summaries are the only
  thing `story_ids_on_issue` can read to know AMS-101..103 already have
  tickets. They were rewritten to `US-` in the same pass; if they ever drift
  from the id format, auto-intake opens duplicate AMS-1041/1042/1043 rows.
- **Do not touch `.py`/`.java`/`DESIGN.md` under `repos/`.** Target-repo source
  is the relevance corpus and is compared byte-for-byte against the codegen
  recordings; editing a comment there shows up as a spurious diff on stage.
  Markdown that is not `DESIGN.md` is safe (`_SOURCE_GLOBS = ("*.py","*.java")`).

Prose inside *generated* documents is a separate problem: `docgen.py`'s calls
pass a fixed `target.cache_key(...)`, and `common/llm.py::complete()` keys its
`.cache/llm/` entry on that alone — prompt content is ignored. The `.cache/llm`
entries were rewritten in place by this rename, but any regenerated entry comes
from the live model and will use whatever the prompt now says.

Seetha also asked for the *release* document to be retitled "Change Request".
That is **deliberately not done** — held by the project owner on 2026-08-03.
Do not apply it without asking.

## Apply restarts the target app, and that is the whole point

Applying rewrites a target's `.py` files, but a running uvicorn keeps serving
the code it imported at startup. Before this existed the console said "the app
now has this capability" while the port still answered with the baseline — the
audience clicks through and sees the old behaviour, which reads as "the change
did nothing". `/s3/apply` now calls `admin_ops.restart_application(...)` and
returns `restarted` / `restarts`.

Three things hold it together:

- **The launch scripts record their PID** (`logs/<service_id>.pid`, written
  before an `exec`, so the PID *is* uvicorn's). `admin_ops.owned_pid` only ever
  stops a process the console holds a PID for — deliberately, so it never kills
  a developer's own process — and before this a service started the documented
  way, `apps/run-*.sh` in a terminal, could never be one of them.
- **A failed restart is reported, never hidden.** `restarted` is false when the
  restart failed *or* could not be attempted (`PROCESS_CONTROL` off, a hardened
  host), and `GenerateStage` then says the app is still on the previous code
  instead of inviting a click-through. Do not collapse those two states into a
  green banner.
- **`tests/conftest.py` stubs `restart_application` suite-wide.** Without it
  `pytest tests/` performs real process control: the first run of this change
  spawned a uvicorn on :8083 and left ClaimsPortal and PolicyCore up. A test
  that wants to exercise restart behaviour patches it with its own fake.

`TARGET_RELOAD=1` in the launch scripts predates this and stays as-is — it needs
`watchfiles`, which is not in `requirements.txt` (hard rule 4), so it cannot be
the default answer.

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
regression suites passed pre- and post-user story. Two traps that pass a `grep` but
break at run time: paths built as split literals (`REPO_ROOT / "apps" /
"policycore"`) are invisible to an `apps/policycore` search, and files with
unusual extensions (`.env.example`, `deploy/aws/*.service`) fall out of an
extension allowlist. Both bit on the first pass. Verify with
`s3_enhancement/discovery.py`-aware end-to-end run, not with grep alone.

## `repos/policycore/app.py` is mirrored inside two recordings

`app.py` is in the `codegen_allowlist` for **both** PolicyCore targets, and both
committed recordings return it as a **whole-file replacement**. So the recorded
copy has to stay equal to the on-disk file plus that user story's delta. Restructure the
portal without re-authoring the recordings and Apply stages a revert of the
restructure — mid-demo, with the diff showing the layout being deleted.

The two live recordings are `s3_enhancement/cache/s3_codegen.json` (US-2026-041,
`cache_namespace=""`) and `s3_codegen__endorsement_field_add.json` (US-2026-042).
Re-author them by applying the user story's delta to the current `app.py` as exact string
substitutions, not by hand-editing the JSON — then assert the replayed diff is
purely additive. **No live re-record is needed**, the same way the two target
moves did not need one. Done once on 2026-08-03 for the sidebar/section
redesign.

Three things make this safe rather than fragile, all verified:
- Replay keys off the **cache namespace, not a prompt hash**
  (`common/llm.py::stream_complete`), so editing `app.py` cannot cause a miss.
- `relevance.select_relevant_files` **excludes core files from the candidate
  pool** before scoring, so `app.py`'s content never shifts which extra files
  are selected — the "unexpected file set" trap does not apply to core files.
- `_drop_unchanged_files` compares against the repo, so a recorded file that
  matches disk is dropped and the diff shows only the user story.

The recordings' JSON encoding is not uniform: the **outer** document is
`ensure_ascii=True`, the **inner** `response` string is `ensure_ascii=False`,
and there is no trailing newline. Round-trip an untouched copy and assert it is
byte-identical before writing, or the diff becomes the whole file.

The two `s3_codegen__revise__*.json` recordings that also carry `app.py`
(`2f4f481…`, `b99921d…`) are **already stale** — they import the pre-reskin
`core.coverage` / `COVERAGE_TIERS` / `holder_name`, which no longer exist. They
predate the GRS reskin and were not repaired by the redesign.

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
HEAD -- <paths>`; a real commit would put the user story into HEAD, so the resets would
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
both pure functions of data already on hand — the changed-file set and the user story
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
removed the only independent check that a user story broke nothing.

Two rules for anything added to them: it must pass **before and after** every
user story (they are invariants, not assertions about the change under test), and it
must stay out of the target roots for the corpus reason above. Both suites
were verified pre-user story, post-user story, and against three injected breakages on
2026-07-29.

## Cross-team impact raises a ticket only for a *code change*

Changed 2026-08-04. The check used to return every system the change touched,
which on US-2026-045 was three — DocumentHub, NightlyBatch, IntegrationBridge —
and put three cards on the board. Two of them were no-ops: NightlyBatch
aggregates by authorising preference into buckets it already has, and
IntegrationBridge carries the preference through on an existing field. Their
numbers move; their code does not. Only DocumentHub has to *author behaviour*
for a case it has never handled.

The bar is now "that team must change code", not "that team is affected", and
it is stated in three places that must stay in step:

- `repos/enroldirect/impact.py::Consumer` carries `changeRequired` +
  `changeRationale`, so a "no" is auditable rather than an omission, and
  `other_teams_requiring_change()` is the short list. All five consumers stay
  in the inventory — the estate map is not the ticket list.
- `analyze.CROSS_TEAM_SYSTEM_PROMPT` and `build_cross_team_prompt` say it to
  the model, in the terms above.
- `tests/test_regression_enroldirect.py` pins it, because the failure is
  silent: nobody notices the extra tickets are fictional until three teams have
  triaged them.

The downstream consequence is also **sized, not described**.
`impact.document_impact()` computes how many confirmation packs would need
wording that does not exist, per option, from the seeded directory — no LLM,
same rule as `diagram.py` and `acceptance.py`. It rides inside
`prospect_impact()["documentImpact"]` rather than on an endpoint of its own,
because a downstream consequence served separately is one a reader can finish
the analysis without having seen. `build_impact_prompt` now asks point 4 for
the named downstream application and its figure, and tells the model to use a
computed one from the context rather than restate the point in general terms.
Both options are priced, not just the recommended one — pricing only the
option you advocate is advocacy.

`CrossTeamImpact` also gained a generated `description` — the body the other
team actually receives. It is a different artifact from `reason`, which
justifies raising the ticket to someone holding the user story; the receiving
engineer has neither the story nor the analysis. Until this change the console
passed `reason` as the description (`useS3Controller.ts`), which handed another
team a one-line ticket they had to come back and ask about. It falls back to
`reason` when absent so an older recording still creates a usable ticket.

## QA can fail a ticket, and the developer it goes back to is derived

`POST /s3/jira/return-to-developer` (the "Failed QA — hand it back" card on the
tester's test stage) is the return leg of the QA hand-off, added 2026-08-04 on
the client's 2026-08-03 walkthrough ask. It reassigns, moves the ticket to **In
Progress** and records the tester's finding in one action — three separate
controls is a hand-back a tester can leave half-done.

`qa_handback.previous_developer` reads the ticket's own assignee history for
the last holder who is neither the current one nor a tester. **Never take that
name from the client** — same rule as `scm.commit_blockers` and the release
record's approvals. Two things it must keep doing: skip testers (a
tester-to-tester second-pair-of-eyes hand-off must not make a tester the
developer), and return 409 rather than guess when there is no earlier
non-tester holder. Permission goes through `_assert_may_reassign`, shared with
`/jira/assign-ticket`, so the fail path can never become a way around the rule
that nobody takes a ticket off a third person.

The recorded reason is numbered (`#2 to Ravi Kumar — …`) because `record_event`
dedups on (ticket, actor, action, detail): the same defect reported twice in
the same words is exactly the history worth keeping.

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
  were never committed, so they are unrecoverable. (Those three were
  ClaimsPortal's, and ClaimsPortal was retired on 2026-08-04, so there is
  nothing left to restore.)
- **`deploy/aws/` is stale and was deliberately left that way on 2026-08-04.**
  Verified that day: the two surviving systemd units *do* carry current paths
  (`apps.console.api.main:app`, `repos/policycore/app.py`) — an earlier version
  of this note claimed they predate the `apps/` restructure, and that was
  wrong. What is actually missing is coverage: no unit and no nginx `location`
  for EnrolDirect or DocumentHub, so the console's `VITE_ENROLDIRECT_URL` /
  `VITE_DOCUMENTHUB_URL` links have no public address on an EC2 deploy. And
  `nginx.conf` proxies `127.0.0.1:8000` / `:8501` while
  `deploy/production/start-apps.sh` defaults to the 20111–20116 block, so the
  two deployment paths cannot be used together unchanged. `deploy/production/`
  itself IS current — DocumentHub is on 20116 in both start and stop scripts.
