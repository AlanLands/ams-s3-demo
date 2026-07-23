# AMS S3 Demo

Standalone build of **S3 (Enhancement)**, split out of the original six-scenario AMS
tabletop demo. Small CR on the "MapleSure Insurance" mock policy/claims app: AI impact
analysis → codegen → tests → docs → release notes.

All data in this repo is synthetic. The demo application belongs to a fictional
insurer, **MapleSure Insurance**. See `CLAUDE.md` for project rules.

`s1_triage/` is present only because the shared login/roster auth
(`s1_triage/roster_auth.py`, `engineer_assignment.py`) lives there — S1 triage itself
is out of scope for this project.

## Setup

```
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in your API key(s)
cd frontend && npm install
```

## Running

Backend: `uvicorn api.main:app --reload` (port 8000)
Frontend (dev): `cd frontend && npm run dev` (port 5173, proxies `/api` to :8000)
Frontend (prod build): `npm run build`, served by the same FastAPI process at :8000

## Layout

- `common/` — LLM provider wrapper (`llm.py`), incident schema, vectorstore, gitlab/
  servicenow clients
- `s3_enhancement/` — the S3 pipeline (analyze, codegen, testgen, harness, docgen, cr)
- `mockapp/` — the MapleSure policy/claims demo app S3 targets
- `s1_triage/` — vendored only for `roster_auth`/`engineer_assignment` (shared login)
- `api/`, `frontend/` — FastAPI backend + React console (Login, Home, S3 only)
- `demo/` — S3 run/reset/cache-warm scripts and presenter notes
- `tools/` — `verify_s3_live.py` (live-demo rehearsal gate), `autofix/` (S3-only
  calibration fix loop)
