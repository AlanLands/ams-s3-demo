"""Live S3 code generation for the coverage-upgrade change.

The model returns complete file replacements for a tight allowlist only. This
module validates the JSON and Python syntax, stages the files, writes an
informational diff, then applies the replacements to the working tree.

The prompt text and validators below (`_validate_file_set`, `_validate_content`,
`_validate_policy_backward_compatible`) are CR-2026-041's specific contract
(exact API names, exact error wording, seed.py backward-compat) — they are not
generic. A second `Target` (see s3_enhancement/targets.py) needs its own
prompt/validator pair to get live codegen; registering a target alone does not
generalize this module's business logic.
"""

from __future__ import annotations

import ast
import difflib
import hashlib
import json
import os
import re
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from common.llm import LLMError, stream_complete
from s3_enhancement import relevance, targets
from s3_enhancement.targets import Target

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_ROOT = REPO_ROOT / "s3_enhancement" / "out"
CACHE_KEY = targets.MOCKAPP_COVERAGE_UPGRADE.stream_cache_key("codegen")
ALLOWLIST = targets.MOCKAPP_COVERAGE_UPGRADE.codegen_allowlist

SYSTEM_PROMPT = (
    "You are an AI pair programmer for a live AMS demo. Return structured JSON "
    "only. Do not include markdown fences, prose, or diffs."
)

_SECRET_RE = re.compile(
    r"(sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----)"
)
_DENYLIST = (
    "real client",
    "end client",
    ".env",
    "api_key",
    "api key",
    "secret",
)


@dataclass
class CodegenResult:
    tier_name: str
    diff_text: str
    files_changed: list[str]
    used_replay: bool
    stream_text_generator: Iterator[str] | None
    selected_files: tuple[str, ...] = ()
    candidate_pool_size: int = 0
    candidate_pool_by_language: dict[str, int] | None = None
    scoped_input_tokens: int | None = None
    scoped_output_tokens: int | None = None
    # True when the token counts are a chars/4 estimate reconstructed from an
    # older replay recording rather than provider-reported usage.
    tokens_estimated: bool = False
    naive_input_tokens_estimate: int = 0
    proposal_id: str = ""
    message: str | None = None
    file_reasons: dict[str, str] | None = None


def propose_change(
    tier_name: str, cr_text: str, *, target: Target | None = None
) -> CodegenResult:
    """Generate, validate, stage, and diff the target's file replacements.

    Does NOT touch the working tree — this is a GitLab-Duo-suggestion-style
    proposal. A human reviews `result.diff_text` (optionally asking for
    tweaks via `revise_change(result.proposal_id, ...)`) and only
    `apply_change(result.proposal_id)` ever writes to the real repo files.
    """
    target = target or targets.get_target(None)
    if os.environ.get("LLM_MODE", "replay").lower() == "replay":
        return _propose_change_once(tier_name, cr_text, target=target, used_replay=True)
    try:
        return _propose_change_once(tier_name, cr_text, target=target, used_replay=False)
    except LLMError:
        with _temporary_env("LLM_MODE", "replay"):
            return _propose_change_once(tier_name, cr_text, target=target, used_replay=True)


def generate_change(
    tier_name: str, cr_text: str, *, target: Target | None = None
) -> CodegenResult:
    """Legacy propose-and-immediately-apply convenience wrapper.

    Kept only for the Streamlit driver console (`s3_enhancement/app.py`),
    which has no review-gate UI of its own. The reviewed API path
    (`api/routers/s3.py`) uses `propose_change()` + `apply_change()`
    separately instead — see their docstrings.
    """
    result = propose_change(tier_name, cr_text, target=target)
    apply_change(result.proposal_id)
    return result


def _propose_change_once(
    tier_name: str, cr_text: str, *, target: Target, used_replay: bool
) -> CodegenResult:
    all_files = relevance.discover_files_for_target(target, cr_text)
    selection = relevance.select_relevant_files(
        cr_text, all_files, core_files=target.core_files
    )
    if target.cache_namespace == targets.MOCKAPP_ENDORSEMENT_FIELD_ADD.cache_namespace:
        prompt = build_endorsement_prompt(cr_text, selection=selection)
    elif target.cache_namespace == targets.SPRINGDEMO_CLAIMS_DEDUCTIBLE.cache_namespace:
        prompt = build_spring_prompt(cr_text, selection=selection)
    else:
        prompt = build_prompt(tier_name, cr_text, selection=selection)
    usage: dict = {}
    substitutions = {"{{TIER_NAME}}": tier_name} if used_replay else None
    chunks: list[str] = []
    try:
        for chunk in stream_complete(
            prompt,
            system=SYSTEM_PROMPT,
            json_mode=True,
            cache_key=target.stream_cache_key("codegen"),
            retries=0,
            replay_substitutions=substitutions,
            chunk_delay=-1,
            usage_out=usage,
        ):
            chunks.append(chunk)
    except LLMError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise LLMError(f"S3 codegen stream failed: {exc}") from exc

    # The recorded/replayed response carries the literal {{TIER_NAME}} token;
    # substitute in every mode so record runs never stage placeholder-bearing
    # files (the replay cache itself is written raw, inside stream_complete,
    # before this line). A live response has no token — no-op.
    response = "".join(chunks).replace("{{TIER_NAME}}", tier_name)
    files, file_reasons = _parse_files_response(response)
    if target.cache_namespace == targets.MOCKAPP_ENDORSEMENT_FIELD_ADD.cache_namespace:
        _validate_endorsement_file_set(files, selection)
    elif target.cache_namespace == targets.SPRINGDEMO_CLAIMS_DEDUCTIBLE.cache_namespace:
        _validate_spring_file_set(files, selection)
    else:
        _validate_file_set(files, selection)
    # Validation runs on the full response (core recall requires every core
    # file back), but the staged proposal should only carry actual pending
    # changes — a file the model returned byte-identical to the repo (or one
    # a previous run already applied) is review noise, not a change.
    files = _drop_unchanged_files(files)
    file_reasons = {path: reason for path, reason in file_reasons.items() if path in files}
    staged_dir = _stage_files(files)
    diff_text = _write_diff(staged_dir, files)
    return CodegenResult(
        tier_name=tier_name,
        diff_text=diff_text,
        files_changed=list(files),
        used_replay=used_replay,
        stream_text_generator=iter(chunks),
        selected_files=tuple(selection.selected),
        candidate_pool_size=selection.candidate_pool_size,
        candidate_pool_by_language=selection.candidate_pool_by_language,
        scoped_input_tokens=usage.get("input_tokens"),
        scoped_output_tokens=usage.get("output_tokens"),
        tokens_estimated=bool(usage.get("estimated")),
        naive_input_tokens_estimate=sum(
            relevance.estimate_tokens(content) for content in all_files.values()
        ),
        proposal_id=staged_dir.parent.name,
        file_reasons=file_reasons,
    )


def _staged_files_on_disk(staged_dir: Path) -> dict[str, str]:
    return {
        str(path.relative_to(staged_dir)): path.read_text(encoding="utf-8")
        for path in sorted(staged_dir.rglob("*"))
        if path.is_file()
    }


def apply_change(proposal_id: str, file_path: str | None = None) -> list[str]:
    """Apply a previously staged proposal to the working tree.

    This is the only function in this module that ever writes to the real
    repo files outside of staging — everything upstream of this
    (`propose_change`, `revise_change`) only ever touches
    `s3_enhancement/out/{proposal_id}/staged/`.

    `file_path`, if given, applies only that one staged file (GitLab/GitHub
    "Apply suggestion" style, file-by-file) instead of the whole proposal —
    safe to call again later for the remaining files, or with no `file_path`
    to apply everything at once; re-applying an already-applied file is a
    no-op copy.
    """
    staged_dir = OUT_ROOT / proposal_id / "staged"
    if not staged_dir.is_dir():
        raise LLMError(f"No staged proposal found for proposal_id {proposal_id!r}")
    files = _staged_files_on_disk(staged_dir)
    if file_path is not None:
        if file_path not in files:
            raise LLMError(
                f"{file_path!r} is not part of staged proposal {proposal_id!r}: "
                f"{sorted(files)}"
            )
        files = {file_path: files[file_path]}
    _apply_staged_files(staged_dir, files)
    return sorted(files)


def revise_change(
    proposal_id: str, instruction: str, *, target: Target | None = None
) -> CodegenResult:
    """Revise a staged (not-yet-applied) proposal per a free-text instruction
    — the ChatGPT/GitLab-Duo-suggestion "ask for a tweak" loop.

    Cost discipline (docs/design/s3_llm_cost_controls.md): only ever sends
    the currently staged file(s) plus the instruction, never the whole repo
    and never a re-fetch of unrelated context — a revision call stays
    roughly the size of the original proposal call, not compounding.
    """
    target = target or targets.get_target(None)
    staged_dir = OUT_ROOT / proposal_id / "staged"
    if not staged_dir.is_dir():
        raise LLMError(f"No staged proposal found for proposal_id {proposal_id!r}")
    staged_files = _staged_files_on_disk(staged_dir)

    prompt = _build_revise_prompt(staged_files, instruction)
    digest = hashlib.sha256(f"{proposal_id}|{instruction}".encode()).hexdigest()[:16]
    cache_key = f"{target.stream_cache_key('codegen')}__revise__{digest}"

    usage: dict = {}
    chunks: list[str] = []
    try:
        for chunk in stream_complete(
            prompt,
            system=SYSTEM_PROMPT,
            json_mode=True,
            cache_key=cache_key,
            retries=0,
            chunk_delay=-1,
            usage_out=usage,
        ):
            chunks.append(chunk)
    except LLMError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise LLMError(f"S3 codegen revise stream failed: {exc}") from exc

    response = "".join(chunks)
    message, revised_files = _parse_revise_response(response)
    unexpected = set(revised_files) - set(staged_files)
    if unexpected:
        raise LLMError(
            f"S3 revise returned files outside the staged proposal: {sorted(unexpected)}"
        )
    for rel_path, content in revised_files.items():
        _validate_content(rel_path, content)
        (staged_dir / rel_path).write_text(content, encoding="utf-8")

    all_files_now = _staged_files_on_disk(staged_dir)
    diff_text = _write_diff(staged_dir, all_files_now)
    return CodegenResult(
        tier_name="",
        diff_text=diff_text,
        files_changed=list(revised_files),
        used_replay=False,
        stream_text_generator=iter(chunks),
        scoped_input_tokens=usage.get("input_tokens"),
        scoped_output_tokens=usage.get("output_tokens"),
        proposal_id=proposal_id,
        message=message,
    )


def _safe_repo_relative_path(rel_path: str) -> str:
    """Resolve a developer-supplied path against REPO_ROOT and reject anything
    that escapes it (absolute paths, `..` traversal, symlink tricks) — this
    path is about to be read from and written into the repo tree, unlike the
    LLM-selected paths elsewhere in this module which are already constrained
    to a fixed allowlist."""
    if os.path.isabs(rel_path):
        raise LLMError(f"{rel_path!r} must be a repo-relative path, not absolute")
    root = REPO_ROOT.resolve()
    resolved = (root / rel_path).resolve()
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError as exc:
        raise LLMError(f"{rel_path!r} resolves outside the repo") from exc


def add_file_to_proposal(proposal_id: str, rel_path: str, instruction: str) -> CodegenResult:
    """Let a developer flag one more file that needs a change to an in-review
    proposal, beyond the AI's original file selection, with a free-text
    instruction for what that change should do.

    Bootstraps the file into the staged proposal (its current on-repo content,
    unchanged) if it isn't already part of it, then delegates to the same
    reviewed ask/revise loop every other staged file already uses — this file
    now behaves exactly like one the AI picked itself: diffable, re-askable,
    and only ever written to the real repo via `apply_change`.
    """
    staged_dir = OUT_ROOT / proposal_id / "staged"
    if not staged_dir.is_dir():
        raise LLMError(f"No staged proposal found for proposal_id {proposal_id!r}")

    rel = _safe_repo_relative_path(rel_path)
    if rel not in _staged_files_on_disk(staged_dir):
        source = REPO_ROOT / rel
        if not source.is_file():
            raise LLMError(f"{rel_path!r} does not exist in the repo")
        staged_path = staged_dir / rel
        staged_path.parent.mkdir(parents=True, exist_ok=True)
        staged_path.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    return revise_change(proposal_id, f"For {rel}: {instruction}")


def _build_revise_prompt(staged_files: dict[str, str], instruction: str) -> str:
    current_files = [f"--- {rel_path} ---\n{content}" for rel_path, content in staged_files.items()]
    json_shape = json.dumps(
        {
            "message": "<1-3 sentence reply to the reviewer>",
            "files": [
                {"path": rel_path, "content": "<complete replacement>"}
                for rel_path in staged_files
            ],
        },
        indent=2,
    )
    return f"""You previously proposed the following file replacements for a live AMS
demo change (not yet applied to the repo):
{chr(10).join(current_files)}

The reviewer wrote this in the "ask about this file" box:
{instruction}

Return structured JSON only with this exact shape:
{json_shape}

Rules:
- "message" always answers or acknowledges the reviewer in plain English. If
  the reviewer asked a question rather than requesting an edit, answer it
  there and omit "files" entirely (or return it empty) — do not change code
  just because a question was asked.
- Only return files from the list above — never introduce a new file path.
- Return each changed file as a complete replacement, not a patch or diff.
- Keep every line at 100 characters or fewer; use modern built-in generics
  (`list[str]`, `X | None`), never `typing.List`/`typing.Optional`.
- Preserve existing docstrings, comments, and house style in spirit; make
  only the change the instruction actually asks for."""


def build_prompt(
    tier_name: str,
    cr_text: str,
    *,
    selection: relevance.SelectionResult | None = None,
    target: Target | None = None,
) -> str:
    if selection is None:
        target = target or targets.get_target(None)
        all_files = relevance.discover_files_for_target(target, cr_text)
        selection = relevance.select_relevant_files(
            cr_text, all_files, core_files=target.core_files
        )

    mode = os.environ.get("LLM_MODE", "replay").lower()
    record_note = ""
    if mode == "record":
        record_note = (
            "\nThe CR contains a placeholder token {{TIER_NAME}}. Reproduce it "
            "verbatim in generated string literals and UI labels; do not invent "
            "a concrete tier name."
        )

    current_files = []
    for rel_path, content in selection.selected.items():
        current_files.append(f"--- {rel_path} ---\n{content}")
    json_shape = json.dumps(
        {
            "files": [
                {
                    "path": rel_path,
                    "content": "<complete replacement>",
                    "reason": "<one short sentence: why this file needs to change>",
                }
                for rel_path in selection.selected
            ]
        },
        indent=2,
    )

    return f"""Change request:
{cr_text}
{record_note}

Audience-selected top tier name: {tier_name}

Current contents of the only files you may replace:
{chr(10).join(current_files)}

Return structured JSON only with this exact shape:
{json_shape}

Rules:
- Return every listed file, each as a complete replacement, not a patch or diff.
- "reason" is one short sentence (plain English, no code) a reviewer can read
  at a glance to know why that specific file is part of this change.
- mockapp/core/coverage.py's public API is a fixed contract other generated
  modules (tests) depend on by these exact names — do not rename or restructure
  them:
  - `COVERAGE_TIERS: list[str]` — ordered lowest to highest, exactly
    `["Standard", "Premium", "{tier_name}"]` (or, only when recording with the
    placeholder CR, `["Standard", "Premium", "{{{{TIER_NAME}}}}"]`).
  - `TIER_MULTIPLIERS: dict[str, float]` — premium multiplier per tier name in
    `COVERAGE_TIERS`.
  - `upgrade_coverage(policy_number: str, new_tier: str) -> Policy` — the only
    function other code calls.
- The top tier name appears only in string literals or list elements, never as
  a Python identifier and never in a path.
- Preserve existing docstrings, comments, and house style in spirit.
- Do not reformat, re-indent, or restructure any line you are not
  intentionally changing for this CR. Every file below uses 4-space
  indentation throughout — match it exactly on every line you output,
  including lines that already existed. Return a minimal, surgical diff
  from the given file content, not a wholesale rewrite.
- Use modern built-in generics for every type hint (`list[str]`,
  `dict[str, float]`, `X | None`) — never `typing.List`, `typing.Dict`,
  `typing.Tuple`, or `typing.Optional`; this repo's ruff config rejects them.
- Keep every line at 100 characters or fewer (this repo's ruff line-length
  limit) — wrap long f-strings, SQL column lists, and comments rather than
  exceeding it.
- mockapp/core/coverage.py must have a module docstring matching the plain
  business-logic tone of mockapp/core/claims.py.
- upgrade_coverage(policy_number, new_tier) must reject unknown tiers, same-tier
  changes, downgrades, and unknown policies with ValueError. Exact error
  wording is a fixed contract (S4's talk-to-code demo cites it):
  - unknown tier: message contains "Unknown coverage tier"
  - same-tier or downgrade: message is
    f"{{policy_number}} is already at {{old_tier!r}}; cannot upgrade to {{new_tier!r}}"
  - unknown policy: message contains "not found"
- Premium must be recalculated as premium / old_multiplier * new_multiplier,
  rounded to 2 decimals with round(..., 2), and persisted with insert_policy().
- Existing policy list, policy detail, claim submission, and claim list flows
  must keep working.
- mockapp/core/seed.py is NOT one of the files you may change, and it
  constructs `Policy(...)` with 6 **positional** arguments in the field order
  shown above (policy_number, holder_name, product_type, premium, start_date,
  status) — no `coverage_tier` argument. You MUST add `coverage_tier` as the
  LAST field on the `Policy` dataclass, after `status`, with a default value
  of `"Standard"` (e.g. `coverage_tier: str = "Standard"`), so those existing
  positional calls keep working unmodified. Do not insert it earlier in the
  field order and do not make it a required (no-default) field."""


def build_endorsement_prompt(
    cr_text: str, *, selection: relevance.SelectionResult
) -> str:
    """Prompt for CR-2026-042 (endorsement priority field) — no audience-picked
    placeholder, unlike the coverage-upgrade CR's {{TIER_NAME}}."""
    current_files = []
    for rel_path, content in selection.selected.items():
        current_files.append(f"--- {rel_path} ---\n{content}")
    json_shape = json.dumps(
        {
            "files": [
                {
                    "path": rel_path,
                    "content": "<complete replacement>",
                    "reason": "<one short sentence: why this file needs to change>",
                }
                for rel_path in selection.selected
            ]
        },
        indent=2,
    )

    return f"""Change request:
{cr_text}

Current contents of the only files you may replace:
{chr(10).join(current_files)}

Return structured JSON only with this exact shape:
{json_shape}

Rules:
- Return every listed file, each as a complete replacement, not a patch or diff.
- "reason" is one short sentence (plain English, no code) a reviewer can read
  at a glance to know why that specific file is part of this change.
- Add a `priority: str = "Standard"` field to the `Endorsement` dataclass in
  mockapp/core/models.py — it must be the LAST field on the dataclass, after
  `filed_at`, with a default value of exactly `"Standard"`. Do not insert it
  earlier in the field order and do not make it a required (no-default) field.
- mockapp/core/db.py: add a `priority` column to the `endorsements` table
  schema (`TEXT NOT NULL DEFAULT 'Standard'`), thread it through
  `_row_to_endorsement()` and `insert_endorsement()`'s column list and
  parameters.
- mockapp/core/endorsements.py: `submit_endorsement(...)` gains a
  `priority: str = "Standard"` keyword parameter (last parameter, defaulted)
  and passes it through to the `Endorsement` it constructs.
- mockapp/app.py: the "Request a Policy Endorsement" form gains a "Priority"
  selectbox with choices exactly `["Standard", "Urgent"]` (in that order, so
  "Standard" is the default selection), and passes the selected value to
  `submit_endorsement(...)`.
- Submitting the form without touching the new Priority control must behave
  exactly as before this CR (defaults to "Standard").
- Preserve existing docstrings, comments, and house style in spirit.
- Do not reformat, re-indent, or restructure any line you are not
  intentionally changing for this CR. Every file below uses 4-space
  indentation throughout — match it exactly on every line you output,
  including lines that already existed. Return a minimal, surgical diff
  from the given file content, not a wholesale rewrite.
- Use modern built-in generics for every type hint (`list[str]`,
  `dict[str, float]`, `X | None`) — never `typing.List`, `typing.Dict`,
  `typing.Tuple`, or `typing.Optional`; this repo's ruff config rejects them.
- Keep every line at 100 characters or fewer (this repo's ruff line-length
  limit) — wrap long f-strings, SQL column lists, and comments rather than
  exceeding it.
- Existing policy list, policy detail, claim submission, and claim list flows
  must keep working, and existing endorsement submissions with no priority
  chosen must still succeed."""


def build_spring_prompt(cr_text: str, *, selection: relevance.SelectionResult) -> str:
    """Prompt for CR-2026-043 (claims deductible) against the Spring Boot
    ClaimsPortal target — Java sources, not Python; no audience-picked
    placeholder, like the endorsement CR."""
    current_files = []
    for rel_path, content in selection.selected.items():
        current_files.append(f"--- {rel_path} ---\n{content}")
    json_shape = json.dumps(
        {
            "files": [
                {
                    "path": rel_path,
                    "content": "<complete replacement>",
                    "reason": "<one short sentence: why this file needs to change>",
                }
                for rel_path in selection.selected
            ]
        },
        indent=2,
    )

    return f"""Change request:
{cr_text}

Current contents of the only files you may replace (an empty file is one the
CR creates from scratch):
{chr(10).join(current_files)}

Return structured JSON only with this exact shape:
{json_shape}

Rules:
- Return every listed file, each as a complete replacement, not a patch or diff.
- "reason" is one short sentence (plain English, no code) a reviewer can read
  at a glance to know why that specific file is part of this change.
- These are Java 21 / Spring Boot 3 sources in two Maven services. Keep each
  file's existing package declaration and imports style; add only the imports
  a change actually needs.
- ClaimRules.java's public API is a fixed contract the generated test suite
  depends on by these exact names — package com.maplesure.claims, class
  ClaimRules, with exactly:
  - `static String decide(String policyStatus, BigDecimal coverageLimit,
    BigDecimal deductible, BigDecimal amount)` returning exactly one of
    "REJECTED_POLICY_" + policyStatus (any non-ACTIVE status),
    "REJECTED_OVER_LIMIT", "REJECTED_BELOW_DEDUCTIBLE", or "ACCEPTED" —
    checked in exactly that precedence order.
  - `static BigDecimal payable(BigDecimal amount, BigDecimal deductible)`
    returning the amount minus the deductible, floored at BigDecimal.ZERO.
- "at or below the deductible" means amount.compareTo(deductible) <= 0 is
  rejected; strictly above the deductible (and within the limit) is accepted.
- Policy.java (policy-service) gains a `BigDecimal deductible` record
  component as the LAST component, after coverageLimit. PolicyController's
  seeded policies use the CR's deductible values. PolicyClient.PolicyView
  (claims-service) gains the matching last component.
- Claim.java gains a `BigDecimal payableAmount` record component as the LAST
  component, after submittedAt. ClaimsController computes the status via
  ClaimRules.decide(...) and payableAmount via ClaimRules.payable(...) for
  accepted claims (BigDecimal.ZERO for rejected claims) — no inline decision
  logic left in the controller.
- Do not touch the static HTML consoles, pom.xml files, or application
  classes — they are not in your file list and must keep working unchanged.
- Preserve existing comments and house style; 4-space indentation throughout,
  matching the given files. Return a minimal, surgical diff from the given
  file content, not a wholesale rewrite.
- Keep every line at 100 characters or fewer.
- Existing flows must keep working: policy list/detail, the claims service's
  policy-directory passthrough, claim submission, and claim listing."""


def _parse_files_response(response: str) -> tuple[dict[str, str], dict[str, str]]:
    """Returns (files, reasons) — `reasons` is the optional one-line "why this
    file changed" the prompt asks for, keyed by path. Older callers that only
    want file content can ignore the second element."""
    text = response.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMError(f"S3 codegen response was not valid JSON: {response[:200]!r}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("files"), list):
        raise LLMError("S3 codegen response must be an object with a files list")

    files: dict[str, str] = {}
    reasons: dict[str, str] = {}
    for item in data["files"]:
        if not isinstance(item, dict):
            raise LLMError("S3 codegen files entries must be objects")
        path = item.get("path")
        content = item.get("content")
        if not isinstance(path, str) or not isinstance(content, str):
            raise LLMError("S3 codegen file entries need string path and content")
        files[path] = content
        reason = item.get("reason")
        if isinstance(reason, str) and reason.strip():
            reasons[path] = reason.strip()
    return files, reasons


def _parse_revise_response(response: str) -> tuple[str | None, dict[str, str]]:
    """Like `_parse_files_response`, but for the "ask about this file" reply:
    tolerates a missing/empty `files` list (a plain question, no edit) and
    also surfaces the model's `message` reply to the reviewer. Older cached
    replay recordings predate the `message` field, so it defaults to None."""
    text = response.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMError(f"S3 codegen response was not valid JSON: {response[:200]!r}") from exc
    if not isinstance(data, dict):
        raise LLMError("S3 codegen response must be a JSON object")

    message = data.get("message")
    if message is not None and not isinstance(message, str):
        raise LLMError("S3 codegen 'message' must be a string")

    raw_files = data.get("files") or []
    if not isinstance(raw_files, list):
        raise LLMError("S3 codegen response 'files' must be a list")

    files: dict[str, str] = {}
    for item in raw_files:
        if not isinstance(item, dict):
            raise LLMError("S3 codegen files entries must be objects")
        path = item.get("path")
        content = item.get("content")
        if not isinstance(path, str) or not isinstance(content, str):
            raise LLMError("S3 codegen file entries need string path and content")
        files[path] = content
    return message, files


def _validate_file_set(files: dict[str, str], selection: relevance.SelectionResult) -> None:
    relevance.verify_core_recall(files, core_files=selection.core_files)
    unexpected = set(files) - set(selection.selected)
    if unexpected:
        raise LLMError(
            "S3 codegen returned unexpected file set: "
            f"outside selected scope {sorted(unexpected)}; selected {sorted(selection.selected)}"
        )
    for rel_path, content in files.items():
        _validate_content(rel_path, content)
    _validate_policy_backward_compatible(files["mockapp/core/models.py"])


def _validate_endorsement_file_set(
    files: dict[str, str], selection: relevance.SelectionResult
) -> None:
    relevance.verify_core_recall(files, core_files=selection.core_files)
    unexpected = set(files) - set(selection.selected)
    if unexpected:
        raise LLMError(
            "S3 codegen returned unexpected file set: "
            f"outside selected scope {sorted(unexpected)}; selected {sorted(selection.selected)}"
        )
    for rel_path, content in files.items():
        _validate_content(rel_path, content)
    _validate_endorsement_priority_field(files["mockapp/core/models.py"])


def _validate_spring_file_set(
    files: dict[str, str], selection: relevance.SelectionResult
) -> None:
    relevance.verify_core_recall(files, core_files=selection.core_files)
    unexpected = set(files) - set(selection.selected)
    if unexpected:
        raise LLMError(
            "S3 codegen returned unexpected file set: "
            f"outside selected scope {sorted(unexpected)}; selected {sorted(selection.selected)}"
        )
    for rel_path, content in files.items():
        _validate_content(rel_path, content)
    _validate_claim_rules_contract(files)


_REQUIRED_CLAIM_RULES_TOKENS = (
    "class ClaimRules",
    "static String decide",
    "static BigDecimal payable",
    "REJECTED_OVER_LIMIT",
    "REJECTED_BELOW_DEDUCTIBLE",
    "ACCEPTED",
)


def _validate_claim_rules_contract(files: dict[str, str]) -> None:
    """CR-2026-043's fixed contract — the generated JUnit suite calls
    ClaimRules.decide/payable by these exact names, and both Policy-side
    records must actually carry the new deductible for the cross-service
    JSON mapping to line up."""
    rules_path = next((path for path in files if path.endswith("ClaimRules.java")), None)
    if rules_path is None:
        raise LLMError("S3 generated file set is missing ClaimRules.java")
    rules = files[rules_path]
    missing = [token for token in _REQUIRED_CLAIM_RULES_TOKENS if token not in rules]
    if missing:
        raise LLMError(
            f"S3 generated ClaimRules.java is missing required contract token(s) {missing}"
        )
    for suffix in ("Policy.java", "PolicyClient.java"):
        path = next((p for p in files if p.endswith(suffix)), None)
        if path is not None and "deductible" not in files[path]:
            raise LLMError(f"S3 generated {suffix} does not carry the new deductible field")


def _validate_endorsement_priority_field(models_content: str) -> None:
    """`priority` must be the Endorsement dataclass's last field, with a
    default — otherwise existing endorsement submissions with no priority
    chosen would break (CR-2026-042's explicit acceptance criterion)."""
    try:
        tree = ast.parse(models_content, filename="mockapp/core/models.py")
    except SyntaxError as exc:
        raise LLMError(f"S3 generated invalid Python for mockapp/core/models.py: {exc}") from exc

    endorsement_cls = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef) and node.name == "Endorsement"
        ),
        None,
    )
    if endorsement_cls is None:
        raise LLMError(
            "S3 generated mockapp/core/models.py is missing the Endorsement dataclass"
        )

    field_stmts = [
        stmt
        for stmt in endorsement_cls.body
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
    ]
    field_names = [stmt.target.id for stmt in field_stmts]
    if not field_names or field_names[-1] != "priority":
        raise LLMError(
            "S3 generated Endorsement.priority must be the last field on the dataclass; "
            f"got field order {field_names}"
        )
    if field_stmts[-1].value is None:
        raise LLMError(
            "S3 generated Endorsement.priority must have a default value, e.g. "
            '`priority: str = "Standard"`'
        )


def _validate_policy_backward_compatible(models_content: str) -> None:
    """mockapp/core/seed.py is off the allowlist and constructs `Policy(...)`
    with 6 positional args (no coverage_tier) — this must still work after the
    generated models.py adds coverage_tier, or the app crashes on startup."""
    namespace: dict = {}
    try:
        exec(compile(models_content, "mockapp/core/models.py", "exec"), namespace)  # noqa: S102
        policy_cls = namespace["Policy"]
        policy_cls("POL-TEST", "Test Holder", "Auto", 100.0, "2024-01-01", "Active")
    except Exception as exc:
        raise LLMError(
            "S3 generated mockapp/core/models.py breaks mockapp/core/seed.py's "
            f"existing 6-positional-arg Policy(...) construction: {exc}"
        ) from exc


_REQUIRED_COVERAGE_SYMBOLS = ("COVERAGE_TIERS", "TIER_MULTIPLIERS", "upgrade_coverage")

# ruff (UP006/UP035) rejects these legacy typing aliases in favor of the
# built-in generics (list[str], dict[str, float], X | None) — catch a live
# slip here rather than shipping non-ruff-clean code, matching every other
# structural check in this function.
_LEGACY_TYPING_ALIASES = frozenset({"List", "Dict", "Tuple", "Set", "FrozenSet", "Optional"})


def _validate_content(rel_path: str, content: str) -> None:
    if rel_path.endswith(".java"):
        _validate_java_content(rel_path, content)
        return
    try:
        tree = ast.parse(content, filename=rel_path)
    except SyntaxError as exc:
        raise LLMError(f"S3 generated invalid Python for {rel_path}: {exc}") from exc

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "typing":
            legacy = {alias.name for alias in node.names} & _LEGACY_TYPING_ALIASES
            if legacy:
                raise LLMError(
                    f"S3 generated legacy typing import in {rel_path}: {sorted(legacy)} — "
                    "use built-in generics (list[str], dict[str, float], X | None) instead"
                )

    lowered = content.lower()
    for forbidden in _DENYLIST:
        if forbidden in lowered:
            raise LLMError(f"S3 generated forbidden string {forbidden!r} in {rel_path}")
    if _SECRET_RE.search(content):
        raise LLMError(f"S3 generated secret-shaped content in {rel_path}")

    if rel_path == "mockapp/core/coverage.py":
        top_level_names = {
            node.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
        } | {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        }
        missing = [name for name in _REQUIRED_COVERAGE_SYMBOLS if name not in top_level_names]
        if missing:
            raise LLMError(
                f"S3 generated mockapp/core/coverage.py is missing required public "
                f"symbol(s) {missing} — got {sorted(top_level_names)}"
            )


def _validate_java_content(rel_path: str, content: str) -> None:
    """Java sources can't go through ast.parse — the real compile check is the
    Maven test run at the /s3/tests beat. This is the cheap structural gate
    the Python path also gets pre-apply: denylist/secret scan, a package
    declaration, and balanced braces (a truncated or fence-mangled response
    fails here instead of at mvn)."""
    lowered = content.lower()
    for forbidden in _DENYLIST:
        if forbidden in lowered:
            raise LLMError(f"S3 generated forbidden string {forbidden!r} in {rel_path}")
    if _SECRET_RE.search(content):
        raise LLMError(f"S3 generated secret-shaped content in {rel_path}")
    if not re.search(r"^package\s+com\.maplesure\.", content, re.M):
        raise LLMError(f"S3 generated {rel_path} without a com.maplesure package declaration")
    stripped = _strip_java_strings_and_comments(content)
    if stripped.count("{") != stripped.count("}"):
        raise LLMError(
            f"S3 generated {rel_path} with unbalanced braces "
            f"({stripped.count('{')} open vs {stripped.count('}')} close)"
        )


_JAVA_NOISE_RE = re.compile(
    r"//[^\n]*"  # line comment
    r"|/\*.*?\*/"  # block comment
    r"|\"(?:\\.|[^\"\\])*\""  # string literal
    r"|'(?:\\.|[^'\\])'",  # char literal
    re.S,
)


def _strip_java_strings_and_comments(content: str) -> str:
    return _JAVA_NOISE_RE.sub("", content)


def _drop_unchanged_files(files: dict[str, str]) -> dict[str, str]:
    """Return only the files whose proposed content actually differs from
    what's on disk right now. A missing repo file (one the CR creates) always
    counts as changed."""
    changed: dict[str, str] = {}
    for rel_path, content in files.items():
        path = REPO_ROOT / rel_path
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if content != current:
            changed[rel_path] = content
    return changed


def _stage_files(files: dict[str, str]) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    staged_dir = OUT_ROOT / stamp / "staged"
    # Always create the directory itself — a proposal where every returned
    # file matched the repo stages zero files but must still be addressable
    # by proposal_id (apply becomes a no-op, not a 502).
    staged_dir.mkdir(parents=True, exist_ok=True)
    for rel_path, content in files.items():
        target = staged_dir / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return staged_dir


def _write_diff(staged_dir: Path, files: dict[str, str]) -> str:
    diff_parts: list[str] = []
    for rel_path in files:
        source_path = REPO_ROOT / rel_path
        staged_path = staged_dir / rel_path
        old = source_path.read_text(encoding="utf-8").splitlines(keepends=True) \
            if source_path.exists() else []
        new = staged_path.read_text(encoding="utf-8").splitlines(keepends=True)
        diff_parts.extend(
            difflib.unified_diff(
                old,
                new,
                fromfile=f"a/{rel_path}",
                tofile=f"b/{rel_path}",
            )
        )
    diff_text = "".join(diff_parts)
    diff_path = staged_dir.parent / "diff.patch"
    diff_path.write_text(diff_text, encoding="utf-8")
    return diff_text


def _apply_staged_files(staged_dir: Path, files: dict[str, str]) -> None:
    for rel_path in files:
        source = staged_dir / rel_path
        target = REPO_ROOT / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


@contextmanager
def _temporary_env(name: str, value: str) -> Iterator[None]:
    old = os.environ.get(name)
    os.environ[name] = value
    try:
        yield
    finally:
        if old is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = old
