# S3 — Technical Reference: Startup & Repository Structure

A code-level tour: exactly what happens when each of the four apps starts,
then every folder in this repo, what's in it, and whether it's actually load-bearing
or leftover from before this repo was trimmed down to S3 only.

---

## Part 1 — Starting each app

### 1. AMS Console — `apps/run-console.sh`

Two processes, one script, `trap 'kill 0' EXIT` stops both together.

```
apps/run-console.sh
  ├─ uvicorn apps.console.api.main:app --port 8000        (backend)
  └─ cd apps/console/web && npm run dev                    (frontend, dev only)
```

**Backend boot** (`apps/console/api/main.py`, executed once at import):
1. `FastAPI()` app constructed.
2. `CORSMiddleware` added — dev-only; once the frontend is built and served by
   this same process, requests are same-origin and it's inert.
3. `auth.router` and `s3.router` mounted under `/api` — deliberately, so a
   frontend route like `/s1` never collides with a backend router of the
   same name (see the module docstring).
4. `GET /api/health` registered.
5. **If** `apps/console/web/dist/` exists (a production build): a catch-all
   `GET /{full_path:path}` is registered *last*, so it only ever catches
   non-`/api` paths — it serves the matching built asset if one exists on
   disk, otherwise `index.html` (SPA history-mode fallback). In local dev
   `dist/` doesn't exist (gitignored, unbuilt), so this route never
   registers — Vite serves the frontend instead, on its own port.

**Frontend boot** (dev only): Vite dev server on `:5173`, proxying `/api/*` to
`:8000` (`vite.config.ts`). First real request from a browser: the React app
loads, calls `GET /api/auth/roster` to populate the login screen.

### 2. PolicyCore — `apps/run-policycore.sh`

```
streamlit run apps/policycore/app.py --server.port 8501
```

**Boot** (`apps/policycore/app.py`):
1. Module-level imports only — no top-level side effects.
2. `if __name__ == "__main__":` sets `st.set_page_config()` once (Streamlit
   forbids calling it twice per session — the guard exists so a
   never-built combined multi-scenario shell could still embed `render()`
   without double-calling it), then calls `render()`.
3. `render()`: `init_db()` first — idempotent (`CREATE TABLE IF NOT EXISTS`
   for `policies`/`claims`/`endorsements`, plus an `ALTER TABLE ADD COLUMN`
   migration if `coverage_tier` is missing from an older `policies` table).
4. Then `inject_theme()`, the policy list, the policy-detail selectbox,
   claims, and the endorsement form, all reading through
   `apps/policycore/core/db.py` — the view itself makes no raw `sqlite3`
   calls.

**One easy-to-miss detail**: `.streamlit/config.toml` sets `runOnSave = true`
— not Streamlit's default. When the S3 pipeline's Apply beat overwrites
`app.py`/`core/*.py` on disk while this process is already running,
`runOnSave` makes it auto-rerun immediately instead of showing a
dismissable "source changed" prompt in the corner. This is why the demo's
Apply beat shows up on screen without a manual restart.

### 3. ClaimsPortal — policy-service — `apps/run-policy-service.sh`

```
uvicorn apps.claimsportal.policy_service.main:app --port 8081
```

**Boot** (`apps/claimsportal/policy_service/main.py`): the `POLICIES` list
and `BY_NUMBER` dict are built **at import time** — plain in-memory data, no
database. Routes (`GET /api/policies`, `GET /api/policies/{policyNumber}`,
`GET /health`, `GET /`) register after. A restart resets state back to the
4 seeded policies — expected, not a bug.

### 4. ClaimsPortal — claims-service — `apps/run-claims-service.sh`

```
uvicorn apps.claimsportal.claims_service.main:app --port 8082
```

**Boot** (`apps/claimsportal/claims_service/main.py`): an empty `CLAIMS` list
and an `itertools.count(1)` id counter, both in-memory. Unlike policy-service,
it does **not** call out to anything at boot — `policy_client.py`'s HTTP
call to policy-service only happens per-request (`GET
/api/claims/policy-directory`, or on `POST /api/claims` to validate). Start
policy-service first, or the first claim submitted while it's still coming
up fails the lookup.

---

## Part 2 — Every folder, top to bottom

### Root files

| File | Purpose |
|---|---|
| `CLAUDE.md` / `AGENTS.md` | Project context and hard rules for an AI agent working in this repo (two names, same content family — `AGENTS.md` is the newer cross-tool convention) |
| `README.md` | Human-facing setup/run/reset instructions |
| `requirements.txt` | Every pinned dependency, one shared venv for all four apps |
| `pyproject.toml` | Just `[tool.pytest.ini_options] testpaths = ["tests"]` — keeps a bare `pytest` from sweeping up generated artifacts under `s3_enhancement/out/` |
| `ruff.toml` | Lint config: `select = ["E","F","I","UP"]`, line-length 100, excludes generated dirs |
| `.env` / `.env.example` | Provider keys and mode flags — never committed with real values (`.env` is gitignored) |
| `.streamlit/config.toml` | `runOnSave = true` (see Part 1, PolicyCore) |
| `.gitignore` | Notably: `data/*`, `.cache/`, `s3_enhancement/out/`, `apps/console/web/dist/`, `apps/console/web/node_modules/`, `.venv/` |

### `apps/` — the four running applications

```
apps/
├── console/
│   ├── api/            FastAPI backend
│   │   ├── main.py          app construction, routing, SPA fallback (Part 1)
│   │   ├── auth.py          roster-based login, session cookie issuance
│   │   ├── session.py       session/cookie helpers
│   │   └── routers/s3.py    every /api/s3/* endpoint — one file, ~30 routes
│   └── web/             React + Vite frontend
│       ├── src/             pages, api.ts/api_s3.ts (thin fetch wrappers), Timeline.tsx, ScmPanel.tsx
│       ├── vite.config.ts   dev server + /api proxy (Part 1)
│       └── dist/            gitignored — production build output, not in the checkout
├── policycore/          PolicyCore — CR-2026-041/042 target
│   ├── app.py               the Streamlit view (Part 1)
│   ├── core/
│   │   ├── models.py         Policy/Claim/Endorsement dataclasses
│   │   ├── db.py             all SQLite access — the view never touches sqlite3 directly
│   │   ├── claims.py          claim-submission business logic
│   │   ├── endorsements.py     endorsement-submission business logic
│   │   ├── seed.py            regenerates data/mockapp.db (18 policies, 6 claims)
│   │   └── coverage.py        CR-2026-041 creates this — absent at baseline
│   ├── crs/                 CR-2026-041.md, CR-2026-042.md — the change-request text itself
│   └── systems/legacy_java_platform/   the relevance-funnel decoy corpus — 6 subsystems
│       (audit, billing, reporting, risk, settlement, underwriting), 58 files, all Java.
│       Exists so the demo can show the AI *not* opening ~50 irrelevant legacy files —
│       see docs/design/S3_DESIGN.md. Not a real app, never runs.
└── claimsportal/        ClaimsPortal — CR-2026-043 target (Python since 2026-07-30)
    ├── policy_service/      policy.py, main.py, static/index.html
    ├── claims_service/      claim.py, policy_client.py, main.py, static/index.html
    │                        (claim_rules.py: created by CR-2026-043, absent at baseline)
    ├── .baseline/           pre-CR snapshot of policy_service/claims_service — what
    │                        demo/reset_s3_springdemo.sh restores
    └── crs/CR-2026-043.md
```

### `s3_enhancement/` — the AI pipeline itself

One module per beat. Everything here is what `apps/console/api/routers/s3.py`
calls into — the router is thin, the logic lives here.

| Module | What it does |
|---|---|
| `targets.py` | The `Target` registry — one entry per CR/repo pairing (`MOCKAPP_COVERAGE_UPGRADE`, `MOCKAPP_ENDORSEMENT_FIELD_ADD`, `SPRINGDEMO_CLAIMS_DEDUCTIBLE`), each declaring its file allowlists, test/regression commands, cache namespace |
| `applications.py` | ServiceNow-CI → application → owning team registry (`routing.py`'s deterministic tier reads this) |
| `routing.py` | Ticket → application resolution (Part 1's Phase-1 beat 1) |
| `repo_match.py` | The AI fallback when routing can't resolve deterministically |
| `analyze.py` | Impact analysis + effort estimate, with the clarifying-question gate |
| `relevance.py` | The relevance funnel — scores every candidate file against the CR text, folds the file path into the scored text deliberately (path carries subsystem signal) |
| `cr.py` | Renders a CR's markdown template, substituting the audience-picked tier name where applicable |
| `codegen.py` | Live codegen: builds the model prompt per target, validates the JSON response, stages files, computes the diff |
| `testgen.py` | Same shape as `codegen.py`, for the generated test file |
| `testrun.py` | Runs a target's test/regression suite (pytest by default; an external `test_command` for anything else) and parses JUnit XML into per-case results |
| `harness.py` | The live agent-harness fallback rung (hardcoded to the mockapp coverage-upgrade target only) |
| `scenarios.py` | Drafts the QA test-scenario plan traced to acceptance criteria |
| `acceptance.py` | Parses a CR's acceptance criteria deterministically — no model call |
| `diagram.py` | Derives the design doc's change-map diagram from the changed-file set — no model call |
| `designdoc.py` | Renders the design doc (HTML + server-side PDF via headless Chromium) |
| `docgen.py` | Drafts release notes (three audiences) and the legacy single-blob variant |
| `traceability.py` | Derives the traceability matrix — criterion → scenario → test → result |
| `design_sync.py` | The design-doc drift check (Phase 3, beat 11) |
| `release.py` | Derives the deployment plan (service-graph order) and assembles the release record, including its "Not evidenced" block |
| `scm.py` / `scm_live.py` | The modelled (never-real) branch → commit → push state machine — see `docs/PIPELINE_FLOW.md` §5 |
| `warm_cache.py` | Pre-warms every narrative beat's replay cache for every registered target (`demo/warm_s3_cache.sh` calls this) |
| `conversation.py`, `quick_chat.py` | The "ask a question about this file" chat affordance in the review stage |
| `screenshots.py` | Attaches a rendered screenshot to a ticket (Jira demo beat) |
| `app.py` | The **legacy** Streamlit driver console — predates the React console, kept only for `demo/run_s3.sh` |

`s3_enhancement/cache/` — committed replay recordings (`s3_codegen__*.json`,
`s3_test_scenarios__*.json`, etc.) that make the demo deterministic offline.
`s3_enhancement/out/` — gitignored, regenerated per run: staged proposals,
diffs, harness runs.

### `common/` — shared clients

| Module | Used by S3? |
|---|---|
| `llm.py` | **Yes, everywhere.** Every LLM call in this repo goes through `complete()`/`stream_complete()`. Provider selection, the replay-cache mechanism, retries. |
| `roster.py` | **Yes.** The fictional login roster + passcode check (`api/auth.py`'s whole auth story). |
| `ticket_events.py` | **Yes.** Append-only ticket timeline — commit gates, QA hand-off, approvals all read this server-side. |
| `jira_client.py` | **Yes.** The mocked (or real, `JIRA_MODE=live`) Jira board S3's tickets live on. |
| `gitlab_client.py` | **Yes**, for the "connect your real GitLab" read-only preview path. |
| `vectorstore.py` | **Yes**, minimally — Chroma-backed, used by one retrieval upgrade. |
| `servicenow_client.py` | **Yes**, minimally — backs the CI/application lookup data shape. |
| `constants.py` | **Yes.** Shared string constants (insurer name, the "AI suggestion" label). |
| `ui_theme.py` | **Yes.** Shared Streamlit visual theme (PolicyCore, the legacy driver console). |
| `telemetry.py` | **Yes**, passively — every `complete()` call logs one JSON line, whether or not anything reads it back today. |
| `schema.py` | **Marginal.** Docstring still describes an S1/S2/S6 incident-record contract generated by a `datagen/` script — but `datagen/` was removed in the six-scenario split. Only remaining reference is `s3_enhancement/scm.py`, reusing a dataclass shape for something unrelated to its original purpose. |
| `ui_pipeline.py`, `ui_timeline.py` | **No.** Zero references anywhere in this repo. Leftover from S1/S2's UI, never used by S3. Kept rather than deleted only because nothing has needed to touch this file since the split. |

### `demo/` — presenter scripts

| Script | Purpose |
|---|---|
| `run_console.sh`†, `run_mockapp.sh`, `run_s3.sh`, `run_s3_harness.sh`, `run_s3_springdemo.sh` | Presenter-facing launch wrappers (mirror `apps/run-*.sh`, some predate it) |
| `reset_s3.sh`, `reset_s3_endorsement.sh`, `reset_s3_springdemo.sh` | Per-target baseline restore — **run in this order**, always |
| `warm_s3_cache.sh` | Pre-warms narrative caches after a reset (`reset_s3.sh` wipes `.cache/llm`) |
| `seed_problem_record_ticket.sh` / `.py` | Seeds the ServiceNow-routing demo ticket |
| `DEMO_STEPS.md` | The from-scratch, section-numbered setup walkthrough — source of truth for `docs/S3_DEMO_STEPS.pdf` |
| `DEMO_TEST_GUIDE.md` | The three-scenario rehearsal script, once you already know the repo |
| `presenter_notes/` | Word-for-word talk track for CR-2026-041 and CR-2026-043's beats |

† `apps/run-console.sh` is the canonical version; some `demo/` scripts predate the `apps/run-*.sh` set and haven't been consolidated.

### `deploy/aws/` — the production path

Systemd units (`ams-s3-console`, `ams-s3-policycore`, `ams-s3-policy-service`,
`ams-s3-claims-service`), `nginx.conf` (single public entry point, path-based
routing to each), `bootstrap.sh` (idempotent provisioning), `README.md`
(step-by-step with verify commands for every step), `bedrock-iam-policy.json`.
See `docs/CODEBASE_AND_DEPLOYMENT.md` for the full story.

### `tests/`

Two kinds, deliberately distinguishable by name:
- `test_s3_*.py` — the pipeline's own unit tests (one file roughly per
  `s3_enhancement/` module), plus `test_api_s3.py` (the FastAPI router,
  end-to-end with mocked LLM calls) and `test_autofix_no_git_writes.py`.
- `test_regression_policycore.py`, `test_regression_claimsportal.py` — the
  target apps' own checked-in, human-authored regression suites. No
  target's `testgen_allowlist`/`codegen_allowlist` names either file — the
  pipeline is structurally unable to write to them.

### `tools/`

| File | Purpose |
|---|---|
| `verify_s3_live.py` + `verify_common.py` | The pre-demo confidence gate — offline architecture checks plus 5x-live narrative-beat checks |
| `cost_dashboard.py` | Reads `common/telemetry.py`'s log for a token-cost summary |
| `render_demo_steps.py` | Renders `demo/DEMO_STEPS.md` → `docs/S3_DEMO_STEPS.{html,pdf}` |
| `autofix/` | Unattended detect → propose → apply → safety-gate → re-verify loop for a failing calibration check (`loop.py`, `propose.py`, `splice.py`, `targets.py`, `adapters/s3.py`) |

### `docs/`

- `APPLICATIONS_AND_ENHANCEMENTS.md` — business/functional view (what each app does, the three CRs, worked examples with screenshots)
- `CODEBASE_AND_DEPLOYMENT.md` — the repo-layout + deployment-readiness doc
- `PIPELINE_FLOW.md` — the 13-beat process walkthrough
- `TECHNICAL_REFERENCE.md` — this document
- `S3_DEMO_STEPS.{html,pdf}`, `S3_TEST_GUIDE.{html,pdf}` — generated/hand-authored presenter documents
- `S3_RANKING_VS_DUO.{html,pdf}`, `S3_REPO_SELECTION.{html,pdf}` — competitive-positioning documents
- `screenshots/` — the images embedded in `APPLICATIONS_AND_ENHANCEMENTS.md`
- `design/` — `S3_DESIGN.md` (the deep architecture doc — relevance scoring internals, validator tables, testrun dispatch), `design_doc_feedback_loop.md`, `s3_llm_cost_controls.md`, `img/`
- `history/` — `SCENARIOS.md`, `README.md` from the original six-scenario repo, kept as background only; explicitly **not** current scope (see `AGENTS.md`)

### `data/` (gitignored, regenerated)

`mockapp.db` (SQLite — PolicyCore's policies/claims/endorsements, rebuilt by
`core/seed.py`), `ticket_events.jsonl` (the ticket audit trail, cleared by
`reset_s3.sh`), `.s3_reset_marker` (a timestamp the console's frontend polls
so it knows to drop stale `localStorage` state after a reset).

### `.cache/` (gitignored, local-machine only)

`llm/` — the narrative-beat replay cache, keyed by a hash of
`provider|model|system|prompt` (see `deploy/aws/README.md` Step 10 for why
this matters under a different provider). `vectordb/` — Chroma's on-disk
store for `common/vectorstore.py`.
