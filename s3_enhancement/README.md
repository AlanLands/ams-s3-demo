# S3 - Enhancement Delivery

Demo beat: a change request lands, the audience chooses a top plan tier
name, and the AMS console generates a real policy-portal enhancement plus tests.

## Scripted Demo Order

1. **CR text** (`crs/CR-2026-041.md`) - rendered by
   `s3_enhancement.cr.render_cr(tier_name)` with the chosen tier name.
2. **AI impact analysis and effort estimate** (`s3_enhancement/analyze.py`) -
   short `complete()` calls using the generic `.cache/llm` store.
3. **AI code generation** (`s3_enhancement/codegen.py`) - streamed full-file JSON
   for exactly four allowlisted files:
   `repos/policycore/core/models.py`, `repos/policycore/core/db.py`,
   `repos/policycore/core/tiers.py`, and `repos/policycore/app.py`.
4. **AI test generation** (`s3_enhancement/testgen.py`) - streamed full-file JSON
   for `tests/test_s3_tier_upgrade.py`.
5. **Tests green** - the S3 console runs
   `python -m pytest tests/test_s3_tier_upgrade.py -v`.
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

## Multi-repo support (`targets.py`, `discovery.py`)

Everything above assumes one repo, one CR. `s3_enhancement/targets.py`
generalizes this: a frozen `Target` (repo root or GitLab `project_id`, CR
template, file allowlists, cache namespace) that every module above accepts
as an optional `target=` param, defaulting to today's one target
(`MOCKAPP_TIER_UPGRADE`) with byte-identical cache keys — no behavior
change for the demo path. `register_target()` makes cache-key collisions
between targets unrepresentable, not just unlikely.

Four targets are registered today: two against `repos/policycore/`
(CR-2026-041, CR-2026-042), one against `repos/claimsportal/` (CR-2026-043)
and one against `repos/enroldirect/` (CR-2026-045).

`discovery.py` removes the code edit. A directory under `repos/` carrying a
`.s3targets.json` manifest is registered at import, so onboarding a repo is a
drop plus a manifest — no `targets.py` change, no redeploy. A manifest that
cannot be parsed **raises at import** rather than being skipped. The manifest
contract and the onboarding steps live in
[`../repos/README.md`](../repos/README.md); they are documented there once, on
purpose. The four built-in targets stay declared by hand because they carry
bespoke codegen file-set validators a manifest cannot express — which is the
one thing that still doesn't generalize. Codegen/testgen's prompts and
validators are per-CR business logic, not automatic.

## CR intake (`cr_intake.py`)

A `.md` file dropped into the top-level `crs/` becomes a board row without
anyone seeding a Jira ticket for it. The key is a pure function of the CR
identifier (`CR-2026-045` → `AMS-1045`), so it survives restarts, resets and
processes — a key that changed between two board loads would strand every
event recorded against the old one. Derived keys start at AMS-1000 because the
seeded demo tickets and `jira_client`'s synthetic replay keys both live in
AMS-100..999. The ticket lands **unassigned**, which routes it to a manager to
assign; nothing here calls an LLM, touches Jira, or writes anything.

## GitLab beat (`relevance.discover_gitlab_files`, `repo_match.py`)

Separate from the scripted PolicyCore demo:
`apps/console/api/routers/s3.py` exposes a read-only "connect your real
GitLab" beat that proves file-discovery economics scale to any repo, without
ever writing generated code back.

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
path applies anything back to GitLab. See
[`../docs/design/S3_DESIGN.md`](../docs/design/S3_DESIGN.md) for the
end-to-end "a CR lands, then what" walkthrough.
