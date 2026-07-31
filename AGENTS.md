# AMS S3 Demo — agent instructions

## Project Context

This repo builds **S3 (Enhancement Delivery) only** — one AI pipeline taking a
small change request on a mock insurance app from impact analysis → code
generation → tests → docs → release notes.

It was split out of an original six-scenario AMS demo repo. The other five
scenarios (S1, S2, S4, S5, S6) are **not** part of this project and are built
elsewhere by the team.

Source of truth:
- `CLAUDE.md` — project context, hard rules, repo layout.
- `README.md` — setup, running, resetting, layout.
- `demo/DEMO_TEST_GUIDE.md` — the three CR scenarios, end to end.
- `docs/history/` — the *original six-scenario* SCENARIOS.md and BUILD_PLAN.md,
  kept as background only. They do not describe current scope.

The fictional demo insurer is **MapleSure Insurance**. Do not name or imply the
real client in code, data, commits, generated UI, screenshots, or docs.

## Hard Rules

1. No real client data, ever. Use synthetic data or public datasets only. If a
   file appears to be a real client export, stop and flag it before processing.
2. No client names in repo content. Refer to the end client only as "the client".
3. API keys and secrets belong in `.env`, loaded through environment variables.
   Never hardcode, print, log, or commit secrets. Keep `.env.example` as
   documentation only.
4. Keep the project portable to a locked-down sandbox: plain Python,
   CSV/SQLite, simple UI, pinned dependencies, no Docker-required flow, no
   machine-specific paths.
5. Demo reliability beats cleverness. The live happy path must work.

## Architecture Direction

- Python 3.12+ with type hints and small modules.
- The console is **React (Vite + TypeScript) over a FastAPI backend** —
  `apps/console/web/` + `apps/console/api/`. Streamlit remains only for the *mock client app*
  (`apps/policycore/app.py`), which is a separate window the demo shows before/after.
- Put pipeline, LLM, data, and domain logic in importable Python modules; keep
  `apps/console/api/` routers thin.
- All LLM calls must go through `common/llm.py`.
- `LLM_PROVIDER` switches provider (Anthropic / OpenAI / Ollama / Bedrock).
  Do not let provider-specific behavior leak outside `common/llm.py`.
- Cache or pin LLM outputs where a demo beat must be deterministic.

## Replay determinism — read before moving files

Every external call (LLM, Jira, GitLab, embeddings) defaults to a committed
**replay** recording under `s3_enhancement/cache/`, so a fresh clone with zero
API keys runs the whole pipeline offline. Two consequences:

- `s3_enhancement/relevance.py::_document()` embeds each file's **path** into
  the text it scores. Renaming or moving a target directory changes the
  embeddings, reshuffles file selection, and desyncs it from the committed
  codegen recordings — the beat then fails hard in replay mode. Moving a target
  is a re-record, not a rename. See `apps/README.md`.
- `common/llm.py`'s `complete()` hashes `cache_key` alone when one is supplied,
  not the prompt. Changing a prompt does **not** invalidate a pinned entry;
  clear `.cache/llm/` when re-testing a changed prompt live.

## Demo Conventions

- Human-in-the-loop everywhere: AI drafts, the engineer reviews and applies.
- Every AI recommendation shown in UI must carry:
  `"AI suggestion - verify with your specialist before applying."`
- Ticket lifecycle ends at resolved + ticket updated. Do not build "close
  ticket" actions; closure stays on the client side.

## Running the App

```bash
uvicorn apps.console.api.main:app --port 8000     # backend — do NOT use --reload (see README)
cd apps/console/web && npm run dev           # console on :5173
demo/run_mockapp.sh                  # the client's app on :8501/sl_policycore, when a beat needs it
```

Reset between rehearsals with `demo/reset_s3.sh`,
`demo/reset_s3_endorsement.sh`, or `demo/reset_s3_springdemo.sh` depending on
the CR. `tools/verify_s3_live.py --skip-live` is the offline rehearsal gate.

## Working Rules

- Before editing, inspect relevant files and `git status --short`.
- Preserve user changes. Do not revert or rewrite unrelated files.
- Prefer existing repo patterns over new abstractions.
- Use `rg`/`rg --files` for search.
- Avoid destructive commands unless explicitly requested.
- Run the narrowest useful validation after changes (`pytest tests/`, `ruff
  check .`). If validation cannot run, say why.
- Do not commit unless the user asks.

## Build Style

- Favor boring, reliable implementation over polished novelty.
- Keep dependencies minimal and pinned in `requirements.txt`.
- Prefer SQLite, local files, and deterministic scripts over managed services.
- Commit message style, when asked to commit:
  `s3: scope relevance funnel to the endorsement form files`.

## `/graphify`

When the user types `/graphify`, invoke the graphify skill before doing
anything else.
