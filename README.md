# AMS S3 Demo

Standalone build of **S3 (Enhancement Delivery)**, split out of the original
six-scenario AMS tabletop demo. A small change request on the "MapleSure
Insurance" mock policy/claims app moves through one pipeline: AI impact
analysis → code generation → tests → docs → release notes.

All data in this repo is synthetic. The demo application belongs to a
fictional insurer, **MapleSure Insurance**. See `CLAUDE.md` for the full
project rules (no real client data, no client names, secrets only via `.env`).

`s1_triage/` is vendored only because the shared login/roster auth
(`s1_triage/roster_auth.py`, `engineer_assignment.py`) lives there — S1
triage itself is out of scope for this project.

## Prerequisites

- **Python 3.12+**
- **Node.js 20+** and npm
- An API key for at least one LLM provider — **Anthropic** or **OpenAI**
  (a local **Ollama** model works too, with no key at all)
- Nothing else is required to run the demo end to end: every external call
  (LLM, Jira, GitLab, vector embeddings) defaults to a committed **replay**
  recording, so a fresh clone with zero keys configured still runs the whole
  pipeline offline.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # fill in ANTHROPIC_API_KEY or OPENAI_API_KEY

cd frontend && npm install && cd ..
```

## Running

```bash
# terminal 1 — backend, port 8000
uvicorn api.main:app --reload

# terminal 2 — frontend dev server, port 5173 (proxies /api to :8000)
cd frontend && npm run dev
```

Open `http://localhost:5173`, log in with a name/passcode from the seeded
roster (see `s1_triage/roster_auth.py` — the passcode scheme is
`1001 + roster position`, e.g. the first engineer is `1001`), and open the
S3 console.

Production build: `cd frontend && npm run build`, then the same
`uvicorn api.main:app` process serves the built app at `:8000` — one process,
one port, no separate frontend server needed.

> **`--reload` caveat:** code generation stages proposals under
> `s3_enhancement/out/`, inside the directory `--reload` watches. Writing a
> proposal can trigger a reload mid-session, which clears the in-memory
> login-session store and 401s the very next request. Drop `--reload` (just
> `uvicorn api.main:app --port 8000`) if you hit an unexpected 401 partway
> through the Generate stage.

### Resetting demo state

The pipeline mutates real files on disk (mockapp source, a SQLite DB, cache
files). Restore everything to its pre-CR baseline between runs:

```bash
demo/reset_s3.sh               # CR-2026-041 target (mockapp coverage upgrade)
demo/reset_s3_springdemo.sh    # CR-2026-043 target (ClaimsPortal, Java/Spring)
```

`demo/warm_s3_cache.sh` pre-warms the LLM and vector-store caches ahead of a
live run, and `tools/verify_s3_live.py` runs the whole pipeline offline with
every live provider path deliberately booby-trapped — the pre-demo
confidence check.

## Layout

- `common/` — LLM provider wrapper (`llm.py`), vector store (`vectorstore.py`),
  Jira/GitLab clients, shared constants and telemetry
- `s3_enhancement/` — the S3 pipeline: `analyze.py` (requirement analysis),
  `codegen.py` (code generation), `testgen.py`/`testrun.py` (test generation,
  execution, and mutation-based proof), `docgen.py` (design doc + release
  notes), `targets.py` (the multi-repo/multi-CR registry), `relevance.py`
  (the file-relevance funnel)
- `mockapp/` — the MapleSure policy/claims app S3 targets modify
- `sandbox/spring-demo/` — the second (Java/Spring Boot) S3 target,
  "ClaimsPortal"
- `s1_triage/` — vendored only for `roster_auth`/`engineer_assignment`
  (shared login)
- `api/`, `frontend/` — FastAPI backend + React console (Login, Home, S3 only)
- `demo/` — run/reset/cache-warm scripts and presenter notes
- `tools/` — `verify_s3_live.py` (live-demo rehearsal gate), `cost_dashboard.py`
  (token-cost reporting), `autofix/` (S3-only calibration fix loop)
- `tests/` — pytest suite covering every module above

## Documentation

- [How the S3 pipeline works](https://claude.ai/code/artifact/917945c7-04e6-4a08-9143-97526cc40b5f) — full product reference: the four phases, tech stack, RAG/vector-search internals, file tour, and how to point this at a different codebase
- [Design notes for recent changes](https://claude.ai/code/artifact/747a6f50-c50a-4eef-acfa-ef4959ebce90) — tests-stage rebuild, ticket-modal UX fixes, LLM cost engineering
- [The same, explained simply](https://claude.ai/code/artifact/b519493a-0aee-4bab-92b1-a2a61b2bd4df) — plain-English, visual version of the above
