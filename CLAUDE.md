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
237 tests pass (`pytest tests/`), ruff clean.

## S3 Enhancement — scope

Small CR on the "MapleSure Insurance" demo app (add a policy/claim capability):
AI analysis → codegen → tests → docs → release notes.

## Layout

```
common/        llm.py (provider wrapper), schema.py, vectorstore.py, gitlab/
               servicenow clients, roster.py (login roster + passcodes) — all
               shared infra
s3_enhancement/  the S3 pipeline: analyze, codegen, testgen, harness, docgen, cr,
                 targets, relevance, repo_match; cache/ (committed replay cache for
                 demo determinism) vs out/ (gitignored, regenerated per run)
mockapp/       "MapleSure" policy/claims app S3 targets for CRs
api/           FastAPI backend — auth.py, session.py, routers/s3.py only
frontend/      React (Vite + TypeScript) console — Login, Home, S3 only
demo/          S3 run/reset/cache-warm scripts + presenter notes
sandbox/       side projects; spring-demo/ is also S3's second target —
               "ClaimsPortal" (Java/Spring Boot, CR-2026-043, ticket AMS-103,
               target id springdemo-claims-deductible). Its checked-in source
               is the pre-CR baseline (snapshot in .baseline/); reset with
               demo/reset_s3_springdemo.sh, run with demo/run_s3_springdemo.sh
tools/         verify_s3_live.py (live-demo rehearsal gate), autofix/ (S3-only
               calibration fix loop — `--scenario` is fixed to s3)
```

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
- `SCENARIOS.md` and `BUILD_PLAN.md` were copied over from the six-scenario repo
  as-is and describe the *original* full scope — treat them as historical
  background, not current scope, until revised.
