# S3 - Enhancement Delivery

Demo beat: a change request lands, the audience chooses a top coverage tier
name, and the AMS console generates a real policy-portal enhancement plus tests.

## Scripted Demo Order

1. **CR text** (`crs/CR-2026-041.md`) - rendered by
   `s3_enhancement.cr.render_cr(tier_name)` with the chosen tier name.
2. **AI impact analysis and effort estimate** (`s3_enhancement/analyze.py`) -
   short `complete()` calls using the generic `.cache/llm` store.
3. **AI code generation** (`s3_enhancement/codegen.py`) - streamed full-file JSON
   for exactly four allowlisted files:
   `apps/policycore/core/models.py`, `apps/policycore/core/db.py`,
   `apps/policycore/core/coverage.py`, and `apps/policycore/app.py`.
4. **AI test generation** (`s3_enhancement/testgen.py`) - streamed full-file JSON
   for `tests/test_s3_coverage_upgrade.py`.
5. **Tests green** - the S3 console runs
   `python -m pytest tests/test_s3_coverage_upgrade.py -v`.
6. **AI release notes** (`s3_enhancement/docgen.py`) - short `complete()` call
   after the change and tests are complete.

## Replay Cache

S3 code/test generation deliberately supports `LLM_MODE=live|record|replay`.
`record` writes full streamed responses to `s3_enhancement/cache/*.json`; these
responses keep the literal `{{TIER_NAME}}` placeholder so one recording can
replay for any audience-selected name via plain string substitution.

The short analysis, effort, and release-note calls intentionally do not use the
S3 replay cache. They stay on `complete()` because they are short narrative
drafts and do not modify files.

## Multi-repo support (`targets.py`)

Everything above assumes one repo, one CR. `s3_enhancement/targets.py`
generalizes this: a frozen `Target` (repo root or GitLab `project_id`, CR
template, file allowlists, cache namespace) that every module above accepts
as an optional `target=` param, defaulting to today's one target
(`MOCKAPP_COVERAGE_UPGRADE`) with byte-identical cache keys — no behavior
change for the demo path. `register_target()` makes cache-key collisions
between targets unrepresentable, not just unlikely. See `DESIGN_MULTI_REPO.md`
for the full writeup (the bug this closes, and what still doesn't
generalize — codegen/testgen's prompts and validators are per-CR business
logic, not automatic).

## GitLab beat (`relevance.discover_gitlab_files`, `repo_match.py`)

Separate from the scripted mockapp demo: `api/routers/s3.py` exposes a
read-only "connect your real GitLab" beat that proves file-discovery
economics scale to any repo, without ever writing generated code back.

- `GET /gitlab/projects` - list connected repos.
- `POST /gitlab/projects/{id}/scope` - manual pick: discover + relevance-score
  files in that one repo.
- `POST /gitlab/scope-auto` - automatic pick: `repo_match.suggest_target_repo`
  asks the LLM to match the CR against every connected repo's
  name/description and return its best guess (+ reasoning + alternates), then
  runs the same discovery/scoping as the manual endpoint. Always labeled as
  an AI suggestion - a human still confirms the pick.

Both paths only ever fetch a shortlist of file contents (TF-IDF pre-rank over
paths first), so cost stays flat regardless of repo count or size. Neither
path applies anything back to GitLab. See `DESIGN_REQUIREMENT_FLOW.md` for the
end-to-end "a CR lands, then what" walkthrough.
