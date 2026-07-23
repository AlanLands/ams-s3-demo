# AMS Tabletop Demo - Codex Instructions

## Project Context

This repo is the seed for a live AMS RFP demo: six AI-driven application-maintenance
scenarios, S1-S6, for a 90-minute customer demo around Wed 22 Jul 2026.

Use these files as the source of truth:
- `CLAUDE.md` - project context, hard rules, repo layout, demo conventions.
- `SCENARIOS.md` - scenario capability decomposition and priorities.
- `BUILD_PLAN.md` - day-by-day build plan and demo flow.

The fictional demo insurer is **MapleSure Insurance**. Do not name or imply the real
client in code, data, commits, generated UI, screenshots, or docs.

## Hard Rules

1. No real client data, ever. Use synthetic data or public datasets only. If a file
   appears to be a real client export, stop and flag it before processing.
2. No client names in repo content. Refer to the end client only as "the client".
3. API keys and secrets belong in `.env`, loaded through environment variables. Never
   hardcode, print, log, or commit secrets. Keep `.env.example` as documentation only.
4. Keep the project portable to a locked-down TCS sandbox: plain Python, CSV/SQLite,
   Streamlit/static/simple UI, pinned dependencies, no Docker-required flow, no
   machine-specific paths.
5. Demo reliability beats cleverness. The 90-minute happy path must work live.

## Architecture Direction

- Python 3.12+ with type hints and small modules.
- Streamlit is the preferred frontend, but keep Streamlit files as thin views.
- Put shared pipeline, LLM, data, and domain logic in importable Python modules.
- All LLM calls must go through `common/llm.py`.
- `LLM_PROVIDER` switches between OpenAI and Anthropic. Default to OpenAI.
- Do not let provider-specific behavior leak outside `common/llm.py`.
- Cache or pin LLM outputs where a live demo beat must be deterministic.
- Use `data/incidents.csv` as the canonical shared dataset for S1, S2, and S6.
- Generated data belongs under `data/`; do not hand-edit generated outputs.

## Demo Conventions

- Human-in-the-loop everywhere: AI drafts, support engineer reviews and sends.
- Every AI recommendation shown in UI must include:
  `"AI suggestion - verify with your specialist before applying."`
- S5 self-healing is recommend-first with an explicit approval gate.
- Do not build or present full autonomous self-healing as live functionality.
- Ticket lifecycle ends at resolved + ticket updated. Do not build "close ticket"
  actions; closure stays on the client side.

## Scenario Priorities

Treat every CORE item in `SCENARIOS.md` as mandatory for the demo. PLUS items are
optional only after CORE paths are stable. TALK items are roadmap narration only.

Required happy-path shape for each scenario:
- One runnable `demo/run_sX.sh` script or equivalent make target.
- One `demo/reset_sX.sh` script to restore pristine rehearsal state.
- Presenter notes or scripted output sufficient for a live walkthrough.
- Cached/pinned LLM output for must-land beats, with live-call fallback.

## Running the App

When asked to run the app/demo, launch only the unified AMS console
(`demo/unified_app.py` via `demo/run_unified.sh`) - one process, one port, S1-S6
behind the sidebar. Do not start per-scenario Streamlit apps alongside it. The
MapleSure mockapp (`mockapp/app.py`) is opened separately only when the S3 beat
needs the client-app before/after proof.

## Codex Working Rules

- Before editing, inspect relevant files and `git status --short`.
- Preserve user changes. Do not revert or rewrite unrelated files.
- Prefer existing repo patterns over new abstractions.
- Keep edits scoped to the scenario or shared module requested.
- Use `rg`/`rg --files` for search.
- Use `apply_patch` for manual edits.
- Avoid destructive commands unless explicitly requested.
- Run the narrowest useful validation after changes. If validation cannot run, say why.
- Do not commit unless the user asks.

## Build Style

- Favor boring, reliable implementation over polished novelty during demo week.
- Keep dependencies minimal and pinned in `requirements.txt`.
- Prefer CSV, SQLite, local files, and deterministic scripts over managed services.
- If a change modifies a seeded data generator, update `datagen/SEEDS.md` in the same
  work and re-verify that S2 still finds the planted clusters.
- Commit message style, when asked to commit: `s2: seed memory-leak cluster in generator`.

## `/graphify`

When the user types `/graphify`, invoke the graphify skill before doing anything else.
