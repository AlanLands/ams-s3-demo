# AMS S3 — Enhancement Delivery

Standalone build of **S3 (Enhancement Delivery)**, split out of the original
six-scenario AMS tabletop walkthrough. A small user story on one of "MapleSure
Insurance"'s group benefits applications moves through one pipeline: AI impact
analysis → code generation → tests → docs → release notes.

All data in this repo is synthetic. The applications belong to a
fictional insurer, **MapleSure Insurance**, and the domain is group retirement
and group benefits — a *plan sponsor* holds a group contract, *plan members*
enrol under it, and a change to an in-force contract is an *amendment*. See
`CLAUDE.md` for the full project rules (no real client data, no client names,
secrets only via `.env`).

> **Setting this up for the first time, or on someone else's machine?**
> Read **[`demo/DEMO_STEPS.md`](demo/DEMO_STEPS.md)** instead — it is the
> step-by-step version of this page, including LLM configuration and
> troubleshooting. A PDF for sharing is at `docs/S3_DEMO_STEPS.pdf`.

## Two folders, and the difference between them

`repos/` holds the applications S3 **changes**. `apps/` holds the tooling that
**does the changing** — the console, and one launch script per process. A
directory dropped into `repos/` with a `.s3targets.json` manifest registers
itself as an S3 target at next start, with no code edit; see
[`repos/README.md`](repos/README.md) for the contract.

Four processes, one launch script each. You do not need all four for every
beat.

| # | Process | Start | Port | Needed for |
|---|-------------|-------|------|------------|
| 1 | **Console** — FastAPI + React. The screen you present from. | `apps/run-console.sh` | 8000 + **5173** | every beat |
| 2 | **PolicyCore** — the client's plan-administration portal (Streamlit) | `apps/run-policycore.sh` | 8501 (open `/sl_policycore`) | US-2026-041, US-2026-042 |
| 3 | **EnrolDirect** — the online enrolment channel (Python/FastAPI) | `apps/run-enroldirect.sh` | 8083 | US-2026-045 |
| 4 | **DocumentHub** — the enrolment document service (Python/FastAPI) | `apps/run-documenthub.sh` | 8084 | US-2026-046 |

ClaimsPortal (US-2026-043, :8081/:8082) was retired on 2026-08-04; its two
launch scripts went with it, which is why the numbering skips nothing but the
port block 8081–8082 is now free.

Open **`http://localhost:5173`** and log in with a name/passcode from
`common/roster.py` (the scheme is `1001 + roster position`, so the first
engineer is `1001`).

A manager also gets **`/admin`** — reset environment state, clear logs, start and stop
processes 2–4, and onboard a repo, without a terminal. See
[`apps/README.md`](apps/README.md) for what it can and deliberately cannot do,
how each application maps to a ServiceNow application, and why the directory
names must not change.

## Prerequisites

- **Python 3.12+**
- **Node.js 20+** and npm
- An LLM provider — Anthropic, OpenAI, Bedrock, Ollama, or any
  OpenAI-compatible endpoint you host yourself (`LLM_PROVIDER=custom`)
- Nothing else. Every external call (LLM, Jira, GitLab, vector embeddings)
  defaults to a committed **replay** recording, so a fresh clone with zero
  keys still runs the whole pipeline offline.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                              # then configure a provider
cd apps/console/web && npm install && cd ../../..
python -m repos.policycore.core.seed
python -m pytest -q                               # expect: 728 passed
```

### Pointing it at your own LLM

For an internal gateway, vLLM, LiteLLM, TGI or LM Studio — anything speaking
the OpenAI chat API:

```bash
LLM_PROVIDER=custom
CUSTOM_LLM_BASE_URL=https://llm.internal.example/v1   # used verbatim; include /v1
CUSTOM_LLM_MODEL=llama-3.3-70b
CUSTOM_LLM_API_KEY=                                   # optional
```

`.env.example` documents every provider block. Note that the *narrative* beats
(impact analysis, effort estimate, release notes) call the provider on a cache
miss even in replay mode — run `demo/warm_s3_cache.sh` before presenting.

## Running

Use the four scripts above. To run the console manually instead:

```bash
uvicorn apps.console.api.main:app --port 8000     # see the --reload caveat below
cd apps/console/web && npm run dev                # :5173, proxies /api to :8000
```

Production build: `cd apps/console/web && npm run build`, then the same
`uvicorn apps.console.api.main:app` process serves the built app at `:8000` —
one process, one port, no separate frontend server.

> **Don't use `--reload` while driving S3.** The S3 pipeline writes `.py`
> files into the tree `--reload` watches, so the app reload-kills its own
> login session: sessions live in an in-memory dict
> (`apps/console/api/session.py`), a reload clears it, and the very next
> request 401s "Not logged in." — while the UI still looks logged in, because
> `AuthContext` only calls `/api/auth/me` once on mount. Two separate stages
> trigger it:
>
> - **Generate** stages the proposal under `s3_enhancement/out/…/staged/`.
> - **Apply** copies staged files onto the real targets —
>   `repos/policycore/app.py`, `repos/policycore/core/*.py`, and a new
>   `tests/test_s3_*.py`.
>
> `--reload-exclude` can't save you: it only helps for `s3_enhancement/out`,
> and Apply writes to the source dirs you'd never exclude. (It also needs an
> *absolute directory* path — uvicorn's `FileFilter` only honours excludes
> that `is_dir()` at startup and compares them against `path.parents`, so a
> glob like `'s3_enhancement/out/*'` silently matches nothing.) Just run
> without `--reload`; restart by hand when you change backend source.

### Resetting environment state

The pipeline mutates real files on disk (application source, a SQLite DB,
cache files). Restore everything to its pre-change baseline between runs — **in
this order**, because the amendment baseline builds on the database
`reset_s3.sh` reseeds:

```bash
demo/reset_s3.sh               # US-2026-041 (PolicyCore plan tier) + shared state
demo/reset_s3_endorsement.sh   # US-2026-042 (PolicyCore amendment priority)
demo/reset_s3_enroldirect.sh   # US-2026-045 (EnrolDirect prospect access)
demo/reset_s3_documenthub.sh   # US-2026-046 (DocumentHub pack wording)
demo/warm_s3_cache.sh          # ALWAYS last — reset_s3.sh wipes .cache/llm
```

> All four resets work. The two PolicyCore ones restore source with `git
> checkout HEAD -- repos/…`, so **HEAD has to carry the paths they name**: any
> time a target moves, commit the move before expecting them to run. (That is
> what bit on 2026-08-03, while the `apps/` → `repos/` move was still
> uncommitted; committing it was the whole fix.) The admin panel checks the
> same condition up front and reports it as `reset_blocked_reason` rather than
> running a script that would fail halfway.
> `reset_s3_enroldirect.sh` and `reset_s3_documenthub.sh` restore by copying
> from their committed `.baseline/` snapshots, so they never depend on HEAD.

A manager can run the same resets from the console's `/admin` panel, one
explicit scope at a time. Source-restoring scopes refuse (409) while the paths
they would overwrite are dirty, and show what they would restore and delete
first.

`tools/verify_s3_live.py` runs the whole pipeline offline with every live
provider path deliberately booby-trapped — the pre-session confidence check.

## Layout

- `repos/` — the target repositories S3 operates on, and the drop folder for
  new ones (see [`repos/README.md`](repos/README.md))
  - `repos/policycore/` — the MapleSure plan-administration portal; S3's first
    target (US-2026-041, US-2026-042). Imported as `repos.policycore.*`
  - `repos/claimsportal/` — S3's second target, "ClaimsPortal" (Python/FastAPI,
    US-2026-043). One folder, two services: the story edits both, so S3
    treats it as a single target root
  - `repos/enroldirect/` — S3's third target, "EnrolDirect" (Python/FastAPI,
    US-2026-045). Its checked-in state is the pre-change baseline, which is a
    *removal*: the impact analysis is done and the gate has not yet been
    changed to act on it
- `stories/` — the user stories. A `.md` dropped in here opens a board ticket
  automatically, keyed off the user story id (`US-2026-045` → `AMS-1045`), and lands
  in the default engineer's To Do column (`STORY_DEFAULT_ASSIGNEE`; empty
  leaves it unassigned for a manager to route)
- `apps/` — the tooling that drives all of the above (see the table and
  `apps/README.md`): `apps/console/api/` + `apps/console/web/` (FastAPI
  backend + React console, including the `/admin` panel) and the launch
  scripts
- `s3_enhancement/` — the S3 pipeline: `analyze.py` (requirement analysis),
  `codegen.py` (code generation, per-file apply/reject/revert),
  `testgen.py`/`testrun.py` (test generation, execution, mutation proof),
  `docgen.py` (design doc + release notes), `targets.py` (the multi-repo /
  multi-user story registry) with `discovery.py` (manifest auto-registration) and
  `story_intake.py` (user story → board ticket), `admin_ops.py` (the admin panel's
  resets, service probes and repo onboarding),
  `applications.py`/`routing.py` (ServiceNow CI → application/team routing),
  `relevance.py` (the file-relevance funnel), `cache/` (committed replay
  recordings — these make the run deterministic)
- `common/` — LLM provider wrapper (`llm.py`), vector store, Jira/GitLab and
  ServiceNow clients, the login roster (`roster.py`), shared constants,
  telemetry
- `demo/` — run/reset/cache-warm scripts, presenter notes, and
  `DEMO_STEPS.md` / `DEMO_TEST_GUIDE.md`
- `tools/` — `verify_s3_live.py` (rehearsal gate), `cost_dashboard.py`
  (token-cost reporting), `render_demo_steps.py` (builds the demo-steps PDF),
  `autofix/`
- `tests/` — the pipeline's own pytest suite **and** each target's
  human-authored regression suite. The regression suites live here, outside
  every target root, on purpose: anything ending `.py` under a target root
  joins the codegen candidate pool, and the pipeline must never be able to
  write to the one independent check that a story broke nothing
- `docs/` — `design/` (current design notes), `history/` (original
  six-scenario planning docs, background only), plus generated PDFs

> **Do not rename directories under `repos/`.** `s3_enhancement/relevance.py`
> folds each file's path into the text it scores, and the committed replay
> recordings contain these exact paths — both as file keys and inside the
> generated code's own `import` statements. A rename desyncs them and the
> codegen beat fails with `codegen returned unexpected file set`. Moving a
> target is a path rewrite across code *and* recordings, not a `mv` — that is
> what the 2026-08-03 `apps/` → `repos/` move actually cost.

## Documentation

- [`demo/DEMO_STEPS.md`](demo/DEMO_STEPS.md) — setup and run steps from a
  clean checkout (PDF: `docs/S3_DEMO_STEPS.pdf`)
- [`demo/DEMO_TEST_GUIDE.md`](demo/DEMO_TEST_GUIDE.md) — per-scenario
  rehearsal script and talk track
- [`repos/README.md`](repos/README.md) — the target repositories, the
  `.s3targets.json` manifest, and how to onboard a new one
- [`apps/README.md`](apps/README.md) — the console, the launch scripts, the
  admin panel, and how each application maps to a ServiceNow application
- [`docs/design/S3_DESIGN.md`](docs/design/S3_DESIGN.md) — technical design
- [How the S3 pipeline works](https://claude.ai/code/artifact/917945c7-04e6-4a08-9143-97526cc40b5f) — full product reference: the four phases, tech stack, RAG/vector-search internals, file tour, and how to point this at a different codebase
- [Design notes for recent changes](https://claude.ai/code/artifact/747a6f50-c50a-4eef-acfa-ef4959ebce90) — tests-stage rebuild, ticket-modal UX fixes, LLM cost engineering
- [The same, explained simply](https://claude.ai/code/artifact/b519493a-0aee-4bab-92b1-a2a61b2bd4df) — plain-English, visual version of the above
