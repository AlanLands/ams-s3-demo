# mockapp — agent-harness instructions for the S3 coverage-upgrade CR

Kept in sync with `apps/policycore/CLAUDE.md` — update both together. This file exists
only for the S3 live agent-harness demo beat (`s3_enhancement/harness.py`); it
does not apply to any other work in this repository.

You are implementing change request `apps/policycore/crs/CR-2026-041.md` (a new top
coverage tier) against this small Python policy/claims mock app for
MapleSure Insurance, a fictional demo insurer. Follow this contract exactly —
it is pinned for a live, timed demo and another generated file
(`tests/test_s3_coverage_upgrade.py`) and a separate scenario (S4) depend on
these exact names and wordings.

## File scope — hard boundary

You may create or edit **only** these files:
- `apps/policycore/core/models.py`
- `apps/policycore/core/db.py`
- `apps/policycore/core/coverage.py`
- `apps/policycore/app.py`
- `tests/test_s3_coverage_upgrade.py`

Do not touch any other file. In particular, `apps/policycore/core/seed.py` is
off-limits — it constructs `Policy(...)` with 6 **positional** arguments
(`policy_number, holder_name, product_type, premium, start_date, status`), no
`coverage_tier` argument. You must add `coverage_tier` as the **last** field on
the `Policy` dataclass, after `status`, with a default value of `"Standard"`
(e.g. `coverage_tier: str = "Standard"`), so `seed.py`'s existing positional
calls keep working unmodified. Do not insert it earlier in the field order and
do not make it a required (no-default) field.

## Fixed public contract — do not rename or restructure

`apps/policycore/core/coverage.py`'s public API is a fixed contract other files
(including the test file you write, and the S4 talk-to-code demo) depend on by
these exact names:

- `COVERAGE_TIERS: list[str]` — ordered lowest to highest, exactly
  `["Standard", "Premium", "<the new top tier name from the CR>"]`.
- `TIER_MULTIPLIERS: dict[str, float]` — premium multiplier per tier name in
  `COVERAGE_TIERS`.
- `upgrade_coverage(policy_number: str, new_tier: str) -> Policy` — the only
  function other code calls.

The top tier name appears only in string literals or list elements, never as a
Python identifier and never in a path.

`upgrade_coverage(policy_number, new_tier)` must reject unknown tiers, same-tier
changes, downgrades, and unknown policies with `ValueError`. The exact wording
is a fixed contract (S4's talk-to-code demo cites it verbatim) — reproduce it
exactly:
- unknown tier: message contains `"Unknown coverage tier"`
- same-tier or downgrade: message is exactly
  `f"{policy_number} is already at {old_tier!r}; cannot upgrade to {new_tier!r}"`
- unknown policy: message contains `"not found"`

Premium must be recalculated as `premium / old_multiplier * new_multiplier`,
rounded to 2 decimals with `round(..., 2)`, and persisted with
`insert_policy()`.

Existing policy list, policy detail, claim submission, and claim list flows in
`apps/policycore/app.py` must keep working.

## Style

- Ruff-clean, every line at 100 characters or fewer.
- Type hints throughout.
- Preserve existing docstrings, comments, and house style in spirit.
- `apps/policycore/core/coverage.py` must have a module docstring matching the plain
  business-logic tone of `apps/policycore/core/claims.py` (no Streamlit or CLI
  concerns in `core/` modules).

## Before finishing

Run `python -m pytest tests/test_s3_coverage_upgrade.py -v` and report the
pass/fail result. Do not consider the task done until it passes.

Do not run `git add`, `git commit`, or `git push`. Leave your changes as
uncommitted working-tree edits — a human reviews the diff before it's treated
as shipped.

## Hard rules for this repo (apply everywhere, not just this CR)

- No real client data or names, ever. This is a synthetic demo for a
  fictional insurer, "MapleSure Insurance." Never write "the client," a real
  company name, or anything that looks like a real client export.
- Never read, print, or write API keys, `.env` contents, or anything
  secret-shaped.
