# AMS S3 Demo

Standalone build of **S3 (Enhancement Delivery)**, split out of the original
six-scenario AMS tabletop demo. A small change request on the "MapleSure
Insurance" mock policy/claims app moves through one pipeline: AI impact
analysis → code generation → tests → docs → release notes.

All data in this repo is synthetic. The demo application belongs to a
fictional insurer, **MapleSure Insurance**. See `CLAUDE.md` for the full
project rules (no real client data, no client names, secrets only via `.env`).

> **Setting this up for the first time, or on someone else's machine?**
> Read **[`demo/DEMO_STEPS.md`](demo/DEMO_STEPS.md)** instead — it is the
> step-by-step version of this page, including LLM configuration and
> troubleshooting. A PDF for sharing is at `docs/S3_DEMO_STEPS.pdf`.

## The four applications

Everything runnable lives under `apps/`, one launch script each. You do not
need all four for every beat.

| # | Application | Start | Port | Needed for |
|---|-------------|-------|------|------------|
| 1 | **Console** — FastAPI + React. The screen you present from. | `apps/run-console.sh` | 8000 + **5173** | every beat |
| 2 | **PolicyCore** — the client's policy portal (Streamlit) | `apps/run-policycore.sh` | 8501 (open `/sl_policycore`) | CR-2026-041, CR-2026-042 |
| 3 | **Policy-Service** — ClaimsPortal policy side (Python/FastAPI) | `apps/run-policy-service.sh` | 8081 | CR-2026-043 |
| 4 | **Claims-Service** — ClaimsPortal claims side (Python/FastAPI) | `apps/run-claims-service.sh` | 8082 | CR-2026-043 |

Open **`http://localhost:5173`** and log in with a name/passcode from
`common/roster.py` (the scheme is `1001 + roster position`, so the first
engineer is `1001`).

See [`apps/README.md`](apps/README.md) for what each folder is, how it maps to
a ServiceNow application, and why the directory names must not change.

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
python -m apps.policycore.core.seed
python -m pytest -q                               # expect: 309 passed
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
>   `apps/policycore/app.py`, `apps/policycore/core/*.py`, and a new
>   `tests/test_s3_*.py`.
>
> `--reload-exclude` can't save you: it only helps for `s3_enhancement/out`,
> and Apply writes to the source dirs you'd never exclude. (It also needs an
> *absolute directory* path — uvicorn's `FileFilter` only honours excludes
> that `is_dir()` at startup and compares them against `path.parents`, so a
> glob like `'s3_enhancement/out/*'` silently matches nothing.) Just run
> without `--reload`; restart by hand when you change backend source.

### Resetting demo state

The pipeline mutates real files on disk (application source, a SQLite DB,
cache files). Restore everything to its pre-CR baseline between runs — **in
this order**, because the endorsement baseline builds on the database
`reset_s3.sh` reseeds:

```bash
demo/reset_s3.sh               # CR-2026-041 (PolicyCore coverage tier) + shared state
demo/reset_s3_endorsement.sh   # CR-2026-042 (PolicyCore endorsement priority)
demo/reset_s3_claimsportal.sh    # CR-2026-043 (ClaimsPortal)
demo/warm_s3_cache.sh          # ALWAYS last — reset_s3.sh wipes .cache/llm
```

`tools/verify_s3_live.py` runs the whole pipeline offline with every live
provider path deliberately booby-trapped — the pre-demo confidence check.

## Layout

- `apps/` — the four runnable applications (see the table above and
  `apps/README.md`). Everything else at the root is tooling, not an app.
  - `apps/console/api/`, `apps/console/web/` — FastAPI backend + React console
  - `apps/policycore/` — the MapleSure policy portal; S3's first target
    (CR-2026-041, CR-2026-042). Imported as `apps.policycore.*`
  - `apps/claimsportal/` — S3's second target, "ClaimsPortal" (Python/FastAPI,
    CR-2026-043). One folder, two services: the CR edits both, so S3
    treats it as a single target root
- `s3_enhancement/` — the S3 pipeline: `analyze.py` (requirement analysis),
  `codegen.py` (code generation, per-file apply/reject/revert),
  `testgen.py`/`testrun.py` (test generation, execution, mutation proof),
  `docgen.py` (design doc + release notes), `targets.py` (the multi-repo /
  multi-CR registry), `applications.py`/`routing.py` (ServiceNow CI →
  application/team routing), `relevance.py` (the file-relevance funnel),
  `cache/` (committed replay recordings — these make the demo deterministic)
- `common/` — LLM provider wrapper (`llm.py`), vector store, Jira/GitLab and
  ServiceNow clients, the login roster (`roster.py`), shared constants,
  telemetry
- `demo/` — run/reset/cache-warm scripts, presenter notes, and
  `DEMO_STEPS.md` / `DEMO_TEST_GUIDE.md`
- `tools/` — `verify_s3_live.py` (rehearsal gate), `cost_dashboard.py`
  (token-cost reporting), `render_demo_steps.py` (builds the demo-steps PDF),
  `autofix/`
- `tests/` — pytest suite covering every module above
- `docs/` — `design/` (current design notes), `history/` (original
  six-scenario planning docs, background only), plus generated PDFs

> **Do not rename directories under `apps/`.** `s3_enhancement/relevance.py`
> folds each file's path into the text it scores, and the committed replay
> recordings contain these exact paths — both as file keys and inside the
> generated code's own `import` statements. A rename desyncs them and the
> codegen beat fails with `codegen returned unexpected file set`. Moving a
> target is a path rewrite across code *and* recordings, not a `mv`.

## Documentation

- [`demo/DEMO_STEPS.md`](demo/DEMO_STEPS.md) — setup and run steps from a
  clean checkout (PDF: `docs/S3_DEMO_STEPS.pdf`)
- [`demo/DEMO_TEST_GUIDE.md`](demo/DEMO_TEST_GUIDE.md) — per-scenario
  rehearsal script and talk track
- [`apps/README.md`](apps/README.md) — the four applications and how they map
  to ServiceNow applications
- [`docs/design/S3_DESIGN.md`](docs/design/S3_DESIGN.md) — technical design
- [How the S3 pipeline works](https://claude.ai/code/artifact/917945c7-04e6-4a08-9143-97526cc40b5f) — full product reference: the four phases, tech stack, RAG/vector-search internals, file tour, and how to point this at a different codebase
- [Design notes for recent changes](https://claude.ai/code/artifact/747a6f50-c50a-4eef-acfa-ef4959ebce90) — tests-stage rebuild, ticket-modal UX fixes, LLM cost engineering
- [The same, explained simply](https://claude.ai/code/artifact/b519493a-0aee-4bab-92b1-a2a61b2bd4df) — plain-English, visual version of the above
