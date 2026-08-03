"""Live S3 code generation for the plan-tier-upgrade change.

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
CACHE_KEY = targets.MOCKAPP_TIER_UPGRADE.stream_cache_key("codegen")
ALLOWLIST = targets.MOCKAPP_TIER_UPGRADE.codegen_allowlist

SYSTEM_PROMPT = (
    "You are an AI pair programmer for a live AMS demo. Return structured JSON "
    "only. Do not include markdown fences, prose, or diffs."
)

# Shared verbatim across every codegen/revise prompt below so the rule can't
# drift between them the way three independently-worded "preserve style"
# bullets did. Whole-file replacement is what makes a model shed this
# material in the first place — asked afterward, it denies removing anything
# — so this is belt-and-suspenders with the deterministic repairs in
# `_restore_module_docstring` / `_restore_body_docstrings` /
# `_format_generated_python`, not a substitute for them: this text only
# reaches a live model, never a replayed one.
_PRESERVATION_RULES = """\
- Treat the given file as an edit target, not a blank page: reproduce every
  line you are not intentionally changing byte-for-byte, including
  blank-line spacing, existing comments, and docstrings. Do not "clean up,"
  reflow, or drop anything the change request did not ask you to touch.
- Every comment and docstring present in the input must still be present in
  your output, unless the exact line(s) it documents no longer exist after
  your change. If a comment or docstring becomes inaccurate because of your
  change, update its wording in place — do not delete it.
- New functions, classes, fields, or parameters you add need a comment or
  docstring in the same style already used in that file (e.g. this file's
  inline `# "A" | "B"` field comments, or a one-sentence docstring for a new
  function/method) — never ship new code with less documentation than what
  already surrounds it."""

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
        cr_text, all_files, core_files=target.core_files, design_doc_root=target.root
    )
    if target.cache_namespace == targets.MOCKAPP_AMENDMENT_FIELD_ADD.cache_namespace:
        prompt = build_amendment_prompt(cr_text, selection=selection)
    elif target.cache_namespace == targets.CLAIMSPORTAL_CLAIMS_DEDUCTIBLE.cache_namespace:
        prompt = build_spring_prompt(cr_text, selection=selection)
    elif target.cache_namespace == targets.ENROLDIRECT_PROSPECT_ACCESS.cache_namespace:
        prompt = build_enroldirect_prompt(cr_text, selection=selection, target=target)
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
    if target.cache_namespace == targets.MOCKAPP_AMENDMENT_FIELD_ADD.cache_namespace:
        _validate_amendment_file_set(files, selection)
    elif target.cache_namespace == targets.CLAIMSPORTAL_CLAIMS_DEDUCTIBLE.cache_namespace:
        _validate_spring_file_set(files, selection)
    elif target.cache_namespace == targets.ENROLDIRECT_PROSPECT_ACCESS.cache_namespace:
        _validate_enroldirect_file_set(files, selection, target)
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
        naive_input_tokens_estimate=relevance.naive_prompt_tokens(
            usage.get("input_tokens"), all_files, selection.selected
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


def stage_files_as_proposal(files: dict[str, str]) -> tuple[str, str]:
    """Stage arbitrary `{repo_relative_path: content}` as a reviewable proposal
    and return `(proposal_id, diff_text)`.

    The seam that lets a non-codegen producer put a change through the same
    review gate the AI's code proposals use — `design_sync.py` stages a
    rewritten `DESIGN.md` this way, so it renders and applies via the existing
    diff/`apply_change()` path instead of needing a second apply mechanism.

    Deliberately does not touch the relevance funnel or any replay cache: a
    proposal staged here is independent of the codegen file-set contract that
    `_validate_file_set` enforces (see design_sync's module docstring for why
    combining them would break the committed recordings).
    """
    staged_dir = _stage_files(files)
    diff_text = _write_diff(staged_dir, files)
    return staged_dir.parent.name, diff_text


def _rejections_path(proposal_id: str) -> Path:
    return OUT_ROOT / proposal_id / "rejections.json"


def rejected_files(proposal_id: str) -> dict[str, str]:
    """`{rel_path: reason}` for every file the developer has rejected on this
    proposal. Empty when nothing has been rejected."""
    path = _rejections_path(proposal_id)
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def reject_file(proposal_id: str, file_path: str, reason: str = "") -> dict[str, str]:
    """Record that the developer rejected one file of a staged proposal.

    A rejection is a decision worth keeping, not just the absence of an apply.
    Before this existed, "I don't want this file" and "I haven't looked at this
    file yet" were the same state on disk, which is precisely the distinction
    an auditor asks about after the fact. `apply_change` then refuses to
    include a rejected file, so "reject" is enforcement rather than a label.

    Reversible via `clear_rejection` — a rejection is the developer's call and
    they are allowed to change their mind before anything is applied.
    """
    staged_dir = OUT_ROOT / proposal_id / "staged"
    if not staged_dir.is_dir():
        raise LLMError(f"No staged proposal found for proposal_id {proposal_id!r}")
    staged = _staged_files_on_disk(staged_dir)
    if file_path not in staged:
        raise LLMError(
            f"{file_path!r} is not part of staged proposal {proposal_id!r}: "
            f"{sorted(staged)}"
        )
    rejections = rejected_files(proposal_id)
    rejections[file_path] = reason.strip()
    _rejections_path(proposal_id).write_text(
        json.dumps(rejections, indent=2), encoding="utf-8"
    )
    return rejections


def clear_rejection(proposal_id: str, file_path: str) -> dict[str, str]:
    """Un-reject a file. No-op if it wasn't rejected."""
    rejections = rejected_files(proposal_id)
    rejections.pop(file_path, None)
    _rejections_path(proposal_id).write_text(
        json.dumps(rejections, indent=2), encoding="utf-8"
    )
    return rejections


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

    Rejected files (see `reject_file`) are excluded from a whole-proposal
    apply, and naming one explicitly is an error rather than an override —
    "apply everything" must never quietly resurrect a change the developer
    already turned down.

    Every file's pre-apply state is backed up first, so `revert_change` can
    put it back.
    """
    staged_dir = OUT_ROOT / proposal_id / "staged"
    if not staged_dir.is_dir():
        raise LLMError(f"No staged proposal found for proposal_id {proposal_id!r}")
    files = _staged_files_on_disk(staged_dir)
    rejections = rejected_files(proposal_id)
    if file_path is not None:
        if file_path not in files:
            raise LLMError(
                f"{file_path!r} is not part of staged proposal {proposal_id!r}: "
                f"{sorted(files)}"
            )
        if file_path in rejections:
            raise LLMError(
                f"{file_path!r} was rejected on proposal {proposal_id!r}; "
                f"clear the rejection before applying it"
            )
        files = {file_path: files[file_path]}
    else:
        files = {path: body for path, body in files.items() if path not in rejections}
    _backup_before_apply(proposal_id, files)
    _apply_staged_files(staged_dir, files)
    return sorted(files)


def _backup_dir(proposal_id: str) -> Path:
    return OUT_ROOT / proposal_id / "backup"


def _absent_manifest_path(proposal_id: str) -> Path:
    """Files that did not exist before this proposal was applied.

    Tracked separately because "no backup content" is ambiguous on its own —
    it could mean a brand-new file or a file whose backup failed to write. A
    revert has to delete the former and must never delete the latter.
    """
    return _backup_dir(proposal_id) / "_absent.json"


def _backup_before_apply(proposal_id: str, files: dict[str, str]) -> None:
    """Snapshot the working-tree state of `files` before they're overwritten.

    First apply of a given file wins: applying, revising, and applying again
    must still revert to the state before *any* of it, not to the intermediate
    version the first apply produced.
    """
    backup_dir = _backup_dir(proposal_id)
    backup_dir.mkdir(parents=True, exist_ok=True)
    absent_path = _absent_manifest_path(proposal_id)
    absent: list[str] = (
        json.loads(absent_path.read_text(encoding="utf-8")) if absent_path.is_file() else []
    )

    for rel_path in files:
        backup_target = backup_dir / rel_path
        if backup_target.exists() or rel_path in absent:
            continue  # already snapshotted by an earlier apply
        source = REPO_ROOT / rel_path
        if source.exists():
            backup_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, backup_target)
        else:
            absent.append(rel_path)

    absent_path.write_text(json.dumps(sorted(set(absent)), indent=2), encoding="utf-8")


def revertable_files(proposal_id: str) -> list[str]:
    """Files this proposal has applied and can still put back."""
    backup_dir = _backup_dir(proposal_id)
    if not backup_dir.is_dir():
        return []
    absent_path = _absent_manifest_path(proposal_id)
    absent: list[str] = (
        json.loads(absent_path.read_text(encoding="utf-8")) if absent_path.is_file() else []
    )
    backed_up = [
        str(path.relative_to(backup_dir))
        for path in sorted(backup_dir.rglob("*"))
        if path.is_file() and path != absent_path
    ]
    return sorted(set(backed_up) | set(absent))


def revert_change(proposal_id: str, file_path: str | None = None) -> list[str]:
    """Undo an applied proposal, restoring the working tree to its pre-apply
    state — the counterpart to `apply_change`, file-by-file or whole.

    Apply writes to the real repo, so without this the only undo was a full
    demo reset (`demo/reset_s3.sh`), which throws away every other beat's state
    too. Reverting a file the proposal *created* deletes it, which is the
    correct inverse of having created it.

    Idempotent: reverting an already-reverted file restores the same backup
    again. The backup is deliberately not cleared, so a mis-click on Revert
    can be followed by Apply and then Revert again.
    """
    backup_dir = _backup_dir(proposal_id)
    available = revertable_files(proposal_id)
    if not available:
        raise LLMError(
            f"Nothing to revert for proposal {proposal_id!r} — it has not been applied"
        )
    if file_path is not None:
        if file_path not in available:
            raise LLMError(
                f"{file_path!r} has not been applied from proposal {proposal_id!r}: "
                f"{available}"
            )
        targets_to_revert = [file_path]
    else:
        targets_to_revert = available

    absent_path = _absent_manifest_path(proposal_id)
    absent: list[str] = (
        json.loads(absent_path.read_text(encoding="utf-8")) if absent_path.is_file() else []
    )

    for rel_path in targets_to_revert:
        live = REPO_ROOT / rel_path
        if rel_path in absent:
            live.unlink(missing_ok=True)
            continue
        shutil.copyfile(backup_dir / rel_path, live)
    return sorted(targets_to_revert)


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

    pending_diff = _compute_diff(staged_dir, staged_files)
    prompt = _build_revise_prompt(staged_files, instruction, pending_diff)
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
        repaired = _repair_generated_content(rel_path, content)
        _validate_content(rel_path, repaired)
        (staged_dir / rel_path).write_text(repaired, encoding="utf-8")

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


def _build_revise_prompt(
    staged_files: dict[str, str], instruction: str, pending_diff: str = ""
) -> str:
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
    # Without the diff the model only ever sees the post-change file, so it
    # cannot tell what it removed — asked "why did you delete X?" it answers
    # from the only text it has and confidently denies the removal. Show it
    # its own diff so "what changed / why" is answerable from evidence.
    diff_section = (
        f"""
This is the diff your proposal produces against the current repo — the
reviewer is looking at exactly this. Lines starting "-" are content you
REMOVED; lines starting "+" are content you ADDED:
{pending_diff}
"""
        if pending_diff.strip()
        else ""
    )
    return f"""You previously proposed the following file replacements for a live AMS
demo change (not yet applied to the repo):
{chr(10).join(current_files)}
{diff_section}
The reviewer wrote this in the "ask about this file" box:
{instruction}

Return structured JSON only with this exact shape:
{json_shape}

Rules:
- "message" always answers or acknowledges the reviewer in plain English. If
  the reviewer asked a question rather than requesting an edit, answer it
  there and omit "files" entirely (or return it empty) — do not change code
  just because a question was asked.
- Answer questions about what changed from the diff above, never from the
  file contents alone. If the reviewer asks why something was removed, read
  the "-" lines: if it really is gone, say so plainly and explain why, and
  do NOT claim it was kept. Never tell the reviewer something is still
  there when the diff shows it removed.
- If the diff removes a docstring, comment, or blank line the change request
  never asked you to touch, that is an unintended regression: say so, and
  return the corrected file in "files" restoring it verbatim.
- Only return files from the list above — never introduce a new file path.
- Return each changed file as a complete replacement, not a patch or diff.
- Keep every line at 100 characters or fewer; use modern built-in generics
  (`list[str]`, `X | None`), never `typing.List`/`typing.Optional`.
{_PRESERVATION_RULES}
- Make only the change the instruction actually asks for."""


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
            cr_text, all_files, core_files=target.core_files, design_doc_root=target.root
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
- repos/policycore/core/tiers.py's public API is a fixed contract other generated
  modules (tests) depend on by these exact names — do not rename or restructure
  them:
  - `PLAN_TIERS: list[str]` — ordered lowest to highest, exactly
    `["Standard", "Premium", "{tier_name}"]` (or, only when recording with the
    placeholder CR, `["Standard", "Premium", "{{{{TIER_NAME}}}}"]`).
  - `TIER_MULTIPLIERS: dict[str, float]` — contribution multiplier per tier name
    in `PLAN_TIERS`.
  - `upgrade_tier(policy_number: str, new_tier: str) -> Policy` — the only
    function other code calls.
- The top tier name appears only in string literals or list elements, never as
  a Python identifier and never in a path.
{_PRESERVATION_RULES}
- Every file below uses 4-space indentation throughout — match it exactly on
  every line you output, including lines that already existed. Return a
  minimal, surgical diff from the given file content, not a wholesale
  rewrite.
- Use modern built-in generics for every type hint (`list[str]`,
  `dict[str, float]`, `X | None`) — never `typing.List`, `typing.Dict`,
  `typing.Tuple`, or `typing.Optional`; this repo's ruff config rejects them.
- Keep every line at 100 characters or fewer (this repo's ruff line-length
  limit) — wrap long f-strings, SQL column lists, and comments rather than
  exceeding it.
- repos/policycore/core/tiers.py must have a module docstring matching the plain
  business-logic tone of repos/policycore/core/claims.py.
- upgrade_tier(policy_number, new_tier) must reject unknown tiers, same-tier
  changes, downgrades, and unknown contracts with ValueError. Exact error
  wording is a fixed contract (S4's talk-to-code demo cites it):
  - unknown tier: message contains "Unknown plan tier"
  - same-tier or downgrade: message is
    f"{{policy_number}} is already at {{old_tier!r}}; cannot upgrade to {{new_tier!r}}"
  - unknown contract: message contains "not found"
- Contribution must be recalculated as
  contribution / old_multiplier * new_multiplier, rounded to 2 decimals with
  round(..., 2), and persisted with insert_policy().
- Existing contract list, contract detail, claim submission, and claim list
  flows must keep working.
- repos/policycore/core/seed.py is NOT one of the files you may change, and it
  constructs `Policy(...)` with 6 **positional** arguments in the field order
  shown above (policy_number, sponsor_name, product_type, contribution,
  start_date, status) — no `plan_tier` argument. You MUST add `plan_tier` as
  the LAST field on the `Policy` dataclass, after `status`, with a default
  value of `"Standard"` (e.g. `plan_tier: str = "Standard"`), so those existing
  positional calls keep working unmodified. Do not insert it earlier in the
  field order and do not make it a required (no-default) field."""


def build_amendment_prompt(
    cr_text: str, *, selection: relevance.SelectionResult
) -> str:
    """Prompt for CR-2026-042 (amendment priority field) — no audience-picked
    placeholder, unlike the tier-upgrade CR's {{TIER_NAME}}."""
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
- Add a `priority: str = "Standard"` field to the `Amendment` dataclass in
  repos/policycore/core/models.py — it must be the LAST field on the dataclass, after
  `filed_at`, with a default value of exactly `"Standard"`. Do not insert it
  earlier in the field order and do not make it a required (no-default) field.
- repos/policycore/core/db.py: add a `priority` column to the `amendments` table
  schema (`TEXT NOT NULL DEFAULT 'Standard'`), thread it through
  `_row_to_amendment()` and `insert_amendment()`'s column list and
  parameters.
- repos/policycore/core/amendments.py: `submit_amendment(...)` gains a
  `priority: str = "Standard"` keyword parameter (last parameter, defaulted)
  and passes it through to the `Amendment` it constructs.
- repos/policycore/app.py: the "Request a Contract Amendment" form gains a "Priority"
  selectbox with choices exactly `["Standard", "Urgent"]` (in that order, so
  "Standard" is the default selection), and passes the selected value to
  `submit_amendment(...)`.
- Submitting the form without touching the new Priority control must behave
  exactly as before this CR (defaults to "Standard").
{_PRESERVATION_RULES}
- Every file below uses 4-space indentation throughout — match it exactly on
  every line you output, including lines that already existed. Return a
  minimal, surgical diff from the given file content, not a wholesale
  rewrite.
- Use modern built-in generics for every type hint (`list[str]`,
  `dict[str, float]`, `X | None`) — never `typing.List`, `typing.Dict`,
  `typing.Tuple`, or `typing.Optional`; this repo's ruff config rejects them.
- Keep every line at 100 characters or fewer (this repo's ruff line-length
  limit) — wrap long f-strings, SQL column lists, and comments rather than
  exceeding it.
- Existing contract list, contract detail, claim submission, and claim list
  flows must keep working, and existing amendment submissions with no priority
  chosen must still succeed."""


def build_spring_prompt(cr_text: str, *, selection: relevance.SelectionResult) -> str:
    """Prompt for CR-2026-043 (claims deductible) against the ClaimsPortal
    target — no audience-picked placeholder, like the amendment CR. Name
    kept from this target's Java-era history (see CLAUDE.md); the source is
    Python since the 2026-07-30 rewrite."""
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
- These are FastAPI sources in two services (policy_service, claims_service).
- claim_rules.py's public API is a fixed contract the generated test suite
  depends on by these exact names — module-level functions, no class:
  - `decide(policy_status: str, coverage_limit: float, deductible: float,
    amount: float) -> str` returning exactly one of
    "REJECTED_POLICY_" + policy_status (any non-ACTIVE status),
    "REJECTED_OVER_LIMIT", "REJECTED_BELOW_DEDUCTIBLE", or "ACCEPTED" —
    checked in exactly that precedence order.
  - `payable(amount: float, deductible: float) -> float` returning the
    amount minus the deductible, floored at zero.
- "at or below the deductible" means `amount <= deductible` is rejected;
  strictly above the deductible (and within the limit) is accepted.
- policy.py's `Policy` model gains a `deductible: float` field as the LAST
  field, after annualMaximum. main.py's seeded contracts use the CR's
  deductible values. policy_client.py's `PolicyView` model gains the
  matching last field.
- claim.py's `Claim` model gains a `payableAmount: float` field as the LAST
  field, after submittedAt. claims_service/main.py computes the status via
  claim_rules.decide(...) and payableAmount via claim_rules.payable(...) for
  accepted claims (0.0 for rejected claims) — no inline decision logic left
  in main.py.
- Do not touch the static HTML consoles — they are not in your file list and
  must keep working unchanged.
{_PRESERVATION_RULES}
- Use modern built-in generics for every type hint (`list[str]`, `dict[str,
  float]`, `X | None`) — never `typing.List`, `typing.Dict`, `typing.Tuple`,
  or `typing.Optional`; this repo's ruff config rejects them.
- Keep every line at 100 characters or fewer (this repo's ruff line-length
  limit) — wrap long f-strings and comments rather than exceeding it.
- Existing flows must keep working: policy list/detail, the claims service's
  policy-directory passthrough, claim submission, and claim listing."""


_ENROLDIRECT_READ_ONLY_REASONS = {
    "repos/enroldirect/impact.py": (
        "the impact analysis this CR acts on — it must keep sizing BOTH "
        "options after one is adopted, and its JSON field names are consumed "
        "by the console"
    ),
    "repos/enroldirect/preferences.py": (
        "the two preference strings are the integration contract with "
        "PolicyCore and arrive verbatim on the contract record — renaming one "
        "silently disables the gate it controls"
    ),
    "repos/enroldirect/benefits.py": (
        "`plans_open_to` already takes an effective category and needs no "
        "change to receive a resolved one"
    ),
}


def build_enroldirect_prompt(
    cr_text: str, *, selection: relevance.SelectionResult, target: Target
) -> str:
    """Prompt for CR-2026-045 (prospect access) against the EnrolDirect target.

    No audience-picked placeholder, like the amendment and ClaimsPortal CRs.

    The instruction with no counterpart in the other builders is the read-only
    set. Three of this target's selected files are context the model needs and
    must not return — `impact.py` above all, since the analysis surface is the
    obvious thing to "finish" and editing it would rewrite the evidence the CR
    is acting on. Editability is read off `target.codegen_allowlist` rather
    than listed here, so the prompt and the validator cannot disagree.
    """
    current_files = []
    for rel_path, content in selection.selected.items():
        marker = "" if rel_path in target.codegen_allowlist else "   [CONTEXT ONLY]"
        current_files.append(f"--- {rel_path} ---{marker}\n{content}")
    editable = [p for p in selection.selected if p in target.codegen_allowlist]
    read_only_rules = "\n".join(
        f"- {rel_path} is CONTEXT ONLY: do not return it and do not change it — "
        f"{_ENROLDIRECT_READ_ONLY_REASONS.get(rel_path, 'it is outside this change')}."
        for rel_path in selection.selected
        if rel_path not in target.codegen_allowlist
    )
    json_shape = json.dumps(
        {
            "files": [
                {
                    "path": rel_path,
                    "content": "<complete replacement>",
                    "reason": "<one short sentence: why this file needs to change>",
                }
                for rel_path in editable
            ]
        },
        indent=2,
    )

    return f"""Change request:
{cr_text}

Current contents of the files in scope. Only the ones NOT marked
[CONTEXT ONLY] may be returned:
{chr(10).join(current_files)}

Return structured JSON only with this exact shape:
{json_shape}

Rules:
- Return every file listed in the shape above, each as a complete replacement,
  not a patch or diff. Return nothing else.
- "reason" is one short sentence (plain English, no code) a reviewer can read
  at a glance to know why that specific file is part of this change.
- These are FastAPI sources for one service (the EnrolDirect enrolment channel).
{read_only_rules}
- applicants.py gains the prospect policy as module-level configuration, not a
  per-call parameter, by these exact names — a fixed contract the generated
  test suite depends on:
  - `TREAT_AS_MEMBER = "MEMBER"` and `TREAT_AS_GUEST = "GUEST"` — the two
    options, whose values are also the effective category each produces.
  - `PROSPECT_POLICIES: tuple[str, ...]` — both options, in that order.
  - `PROSPECT_POLICY` — the policy in force, set to `TREAT_AS_GUEST`.
- eligibility.py:
  - `preference_for_category(category: str) -> str | None` keeps its single
    parameter. MEMBER resolves to MEMBER_ACCESS, GUEST to GUEST_ACCESS, and
    PROSPECT resolves through `PROSPECT_POLICY` to MEMBER_ACCESS when the
    policy is `TREAT_AS_MEMBER` and GUEST_ACCESS otherwise. Anything else
    still returns None.
  - add `effective_category(category: str) -> str` — the category an applicant
    is treated as: a prospect's is `PROSPECT_POLICY`'s value, everyone else's
    is their own category.
  - `EligibilityDecision` gains `prospectPolicyApplied: str | None`, populated
    with `PROSPECT_POLICY` for prospects and None for every other category, on
    every return path including the denials.
  - The three gates keep their existing order: contract status first, then the
    category-to-preference resolution, then the sponsor's enabled preferences.
    A prospect on a LAPSED contract must still be denied at the first gate.
- enrolments.py resolves the effective category once via
  `eligibility.effective_category` and uses it for the member-only plan check
  (`plan.memberOnly and effective != "MEMBER"`). `EnrolmentRecord` gains
  `effectiveCategory: str` and `prospectPolicyApplied: str | None`, both
  placed after `category`. The access gate is reused, never reimplemented.
- main.py's `/api/eligibility/check` response gains `prospectPolicyApplied`
  from the decision. `/api/applicants/{{applicant_id}}/plans` resolves the
  effective category, filters `benefits.plans_open_to` on it, and returns it
  as `effectiveCategory` alongside the existing `category`. No request model
  gains a prospect-policy field — the gate enforces one policy.
- Do not add an endpoint that sets or overrides the policy.
- Do not touch the static HTML console — it is not in your file list and must
  keep working unchanged.
- Imports are where this change goes wrong. Two files have exactly one correct
  import statement each, and rewriting either of them differently is a
  NameError at request time rather than a test failure you would see here.
  Reproduce these two lines verbatim:
  - eligibility.py — replace its existing
    `from repos.enroldirect.applicants import GUEST, MEMBER, Applicant`
    with exactly:
    `from repos.enroldirect.applicants import (GUEST, MEMBER, PROSPECT,
    PROSPECT_POLICY, TREAT_AS_MEMBER, Applicant)` — wrapped across lines in
    that order. `Applicant` is still used by `check_eligibility`'s signature
    and must not be dropped. Do not import `TREAT_AS_GUEST`; the code compares
    against `TREAT_AS_MEMBER` only.
  - enrolments.py — its import of eligibility becomes exactly
    `from repos.enroldirect.eligibility import check_eligibility,
    effective_category`. Add nothing else to it.
- In enrolments.py's member-only check, KEEP the existing `"MEMBER"` string
  literal and change only the left-hand side: `if plan.memberOnly and
  applicant.category != "MEMBER":` becomes
  `if plan.memberOnly and effective != "MEMBER":`. Do not replace the literal
  with a bare `MEMBER` name — it is not imported in that file.
- A dataclass field with no default cannot follow one that has a default —
  `EligibilityDecision.reasons` already has `field(default_factory=list)`, so
  put any new field BEFORE it, not after.
- applicants.py's module docstring currently states that no preference has
  been assigned to prospects and that the gate refuses them. That is no longer
  true after this change — rewrite that paragraph to describe the policy now
  in force. Leave the rest of the docstring alone.
{_PRESERVATION_RULES}
- Use modern built-in generics for every type hint (`list[str]`, `dict[str,
  float]`, `X | None`) — never `typing.List`, `typing.Dict`, `typing.Tuple`,
  or `typing.Optional`; this repo's ruff config rejects them.
- Keep every line at 100 characters or fewer (this repo's ruff line-length
  limit) — wrap long f-strings and comments rather than exceeding it.
- Existing flows must keep working: the contract and applicant directories,
  the access check for members and guests, the benefit catalogue, enrolment
  submission and refusal recording, and the analysis endpoints."""


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
    _validate_policy_backward_compatible(files["repos/policycore/core/models.py"])


def _validate_enroldirect_file_set(
    files: dict[str, str], selection: relevance.SelectionResult, target: Target
) -> None:
    """File-set check for a target whose prompt shows a file it may not change.

    `impact.py` is one of this target's `core_files` — the model has to read
    the analysis to understand what the CR is acting on — but it is not in the
    `codegen_allowlist`, so demanding it back the way `verify_core_recall`
    does for every other target would fail every well-behaved response. Core
    recall therefore runs over the editable core files only.

    The read-only files are still checked, in the direction that matters: the
    model may echo one back unchanged (harmless, and `_drop_unchanged_files`
    removes it), but a *modified* one is the CR's "not to be changed by this
    CR" clause being broken, and that fails loudly rather than being silently
    discarded.
    """
    editable_core = tuple(p for p in selection.core_files if p in target.codegen_allowlist)
    relevance.verify_core_recall(files, core_files=editable_core)

    unexpected = set(files) - set(selection.selected)
    if unexpected:
        raise LLMError(
            "S3 codegen returned unexpected file set: "
            f"outside selected scope {sorted(unexpected)}; selected {sorted(selection.selected)}"
        )

    modified_read_only = sorted(
        rel_path
        for rel_path, content in files.items()
        if rel_path not in target.codegen_allowlist
        and content != selection.selected.get(rel_path)
    )
    if modified_read_only:
        raise LLMError(
            "S3 codegen modified files this CR forbids changing: "
            f"{modified_read_only}; allowlist {sorted(target.codegen_allowlist)}"
        )

    for rel_path, content in files.items():
        _validate_content(rel_path, content)


def _validate_amendment_file_set(
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
    _validate_amendment_priority_field(files["repos/policycore/core/models.py"])


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


def _validate_claim_rules_contract(files: dict[str, str]) -> None:
    """CR-2026-043's fixed contract — the generated pytest suite calls
    claim_rules.decide/payable by these exact names, and both Policy-side
    models must actually carry the new deductible for the cross-service
    JSON mapping to line up."""
    rules_path = next((path for path in files if path.endswith("claim_rules.py")), None)
    if rules_path is None:
        raise LLMError("S3 generated file set is missing claim_rules.py")
    rules = files[rules_path]
    try:
        tree = ast.parse(rules, filename=rules_path)
    except SyntaxError as exc:
        raise LLMError(f"S3 generated invalid Python for {rules_path}: {exc}") from exc

    def_names = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    missing_defs = {"decide", "payable"} - def_names
    if missing_defs:
        raise LLMError(f"S3 generated claim_rules.py is missing function(s) {sorted(missing_defs)}")

    required_tokens = ("REJECTED_OVER_LIMIT", "REJECTED_BELOW_DEDUCTIBLE", "ACCEPTED")
    missing_tokens = [token for token in required_tokens if token not in rules]
    if missing_tokens:
        raise LLMError(
            f"S3 generated claim_rules.py is missing required contract token(s) {missing_tokens}"
        )
    for suffix in ("policy.py", "policy_client.py"):
        path = next((p for p in files if p.endswith(suffix)), None)
        if path is not None and "deductible" not in files[path]:
            raise LLMError(f"S3 generated {suffix} does not carry the new deductible field")


def _validate_amendment_priority_field(models_content: str) -> None:
    """`priority` must be the Amendment dataclass's last field, with a
    default — otherwise existing amendment submissions with no priority
    chosen would break (CR-2026-042's explicit acceptance criterion)."""
    try:
        tree = ast.parse(models_content, filename="repos/policycore/core/models.py")
    except SyntaxError as exc:
        raise LLMError(f"S3 generated invalid Python for repos/policycore/core/models.py: {exc}") from exc

    amendment_cls = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef) and node.name == "Amendment"
        ),
        None,
    )
    if amendment_cls is None:
        raise LLMError(
            "S3 generated repos/policycore/core/models.py is missing the Amendment dataclass"
        )

    field_stmts = [
        stmt
        for stmt in amendment_cls.body
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
    ]
    field_names = [stmt.target.id for stmt in field_stmts]
    if not field_names or field_names[-1] != "priority":
        raise LLMError(
            "S3 generated Amendment.priority must be the last field on the dataclass; "
            f"got field order {field_names}"
        )
    if field_stmts[-1].value is None:
        raise LLMError(
            "S3 generated Amendment.priority must have a default value, e.g. "
            '`priority: str = "Standard"`'
        )


def _validate_policy_backward_compatible(models_content: str) -> None:
    """repos/policycore/core/seed.py is off the allowlist and constructs `Policy(...)`
    with 6 positional args (no plan_tier) — this must still work after the
    generated models.py adds plan_tier, or the app crashes on startup."""
    namespace: dict = {}
    try:
        exec(compile(models_content, "repos/policycore/core/models.py", "exec"), namespace)  # noqa: S102
        policy_cls = namespace["Policy"]
        policy_cls("POL-TEST", "Test Sponsor Ltd.", "Health", 100.0, "2024-01-01", "Active")
    except Exception as exc:
        raise LLMError(
            "S3 generated repos/policycore/core/models.py breaks repos/policycore/core/seed.py's "
            f"existing 6-positional-arg Policy(...) construction: {exc}"
        ) from exc


_REQUIRED_TIER_SYMBOLS = ("PLAN_TIERS", "TIER_MULTIPLIERS", "upgrade_tier")

# ruff (UP006/UP035) rejects these legacy typing aliases in favor of the
# built-in generics (list[str], dict[str, float], X | None) — catch a live
# slip here rather than shipping non-ruff-clean code, matching every other
# structural check in this function.
_LEGACY_TYPING_ALIASES = frozenset({"List", "Dict", "Tuple", "Set", "FrozenSet", "Optional"})


def _validate_content(rel_path: str, content: str) -> None:
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

    if rel_path == "repos/policycore/core/tiers.py":
        top_level_names = {
            node.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
        } | {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        }
        missing = [name for name in _REQUIRED_TIER_SYMBOLS if name not in top_level_names]
        if missing:
            raise LLMError(
                f"S3 generated repos/policycore/core/tiers.py is missing required public "
                f"symbol(s) {missing} — got {sorted(top_level_names)}"
            )


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


def _restore_module_docstring(rel_path: str, content: str) -> str:
    """Put back a module docstring the model dropped on its way through a
    whole-file replacement.

    Returning each file as a complete replacement makes models silently shed
    the leading docstring, and no prompt rule reliably stops it: asked about
    the deletion they deny it, and told to fix it they echo the same content
    back while reporting success. The CR never asks to delete a docstring, so
    treat its disappearance as an artefact of the format and repair it here
    instead of trusting the model to.
    """
    if not rel_path.endswith(".py"):
        return content
    source_path = REPO_ROOT / rel_path
    if not source_path.exists():
        return content
    try:
        original = source_path.read_text(encoding="utf-8")
        original_tree = ast.parse(original, filename=rel_path)
        if ast.get_docstring(original_tree) is None:
            return content
        if ast.get_docstring(ast.parse(content, filename=rel_path)) is not None:
            return content
    except (SyntaxError, ValueError):
        # Invalid Python is _validate_content's problem to report, not ours.
        return content
    end_lineno = getattr(original_tree.body[0], "end_lineno", None)
    if end_lineno is None:
        return content
    docstring_block = "".join(original.splitlines(keepends=True)[:end_lineno])
    return f"{docstring_block}\n{content.lstrip(chr(10))}"


def _qualified_docstring_owners(
    tree: ast.Module,
) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef]:
    """Dotted-name -> node for every function/class in `tree`, e.g.
    `"Amendment"` or `"Foo.bar"` for a method `bar` on class `Foo`. Used to
    match a function/class between the original file and the model's
    replacement by name rather than by position, since the model is free to
    reorder or insert around it."""
    owners: dict[str, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef] = {}

    def visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                qualname = f"{prefix}{child.name}"
                owners[qualname] = child
                visit(child, f"{qualname}.")

    visit(tree, "")
    return owners


def _restore_body_docstrings(rel_path: str, content: str) -> str:
    """Put back function/class docstrings the model dropped, the same way
    `_restore_module_docstring` does for the module docstring — whole-file
    replacement sheds these just as readily, and it is the exact regression
    reported against CR-2026-042's replay: docstrings gone from every touched
    function, not only the module's.

    Matches functions/classes by qualified name only. A function the model
    renamed, removed, or nested differently gets no repair — that is either
    a real edit or something `_validate_content`/the test suite should catch
    on its own, not something to paper over here.
    """
    if not rel_path.endswith(".py"):
        return content
    source_path = REPO_ROOT / rel_path
    if not source_path.exists():
        return content
    try:
        original = source_path.read_text(encoding="utf-8")
        original_tree = ast.parse(original, filename=rel_path)
        generated_tree = ast.parse(content, filename=rel_path)
    except (SyntaxError, ValueError):
        # Invalid Python is _validate_content's problem to report, not ours.
        return content

    original_lines = original.splitlines(keepends=True)
    generated_lines = content.splitlines(keepends=True)
    original_owners = _qualified_docstring_owners(original_tree)
    generated_owners = _qualified_docstring_owners(generated_tree)

    # Collected then applied bottom-up (by generated line number) so an
    # earlier insertion never shifts the line numbers still to be inserted.
    insertions: list[tuple[int, str]] = []
    for qualname, orig_node in original_owners.items():
        if not orig_node.body or ast.get_docstring(orig_node) is None:
            continue
        gen_node = generated_owners.get(qualname)
        if gen_node is None or not gen_node.body or ast.get_docstring(gen_node) is not None:
            continue
        doc_stmt = orig_node.body[0]
        doc_end = getattr(doc_stmt, "end_lineno", None)
        if doc_end is None:
            continue
        block = "".join(original_lines[doc_stmt.lineno - 1 : doc_end])
        target_indent = " " * gen_node.body[0].col_offset
        reindented = "".join(
            f"{target_indent}{line.lstrip(' ')}" if line.strip() else line
            for line in block.splitlines(keepends=True)
        )
        insertions.append((gen_node.body[0].lineno - 1, reindented))

    if not insertions:
        return content
    for insert_at, block in sorted(insertions, key=lambda pair: pair[0], reverse=True):
        generated_lines.insert(insert_at, block)
    return "".join(generated_lines)


def _restore_dropped_comment_lines(rel_path: str, content: str) -> str:
    """Restore whole-line comments a whole-file replacement silently dropped
    anywhere in the file — not just docstrings. Found against a real
    recording (CR-2026-042): a design-rationale comment in the middle of a
    function body vanished with no docstring involved, so the AST-based
    docstring repairs above never see it.

    Uses a plain line-level diff (`difflib`) against the original file: a
    contiguous block the model deleted is only restored if it consists
    entirely of comment/blank lines. A deleted block containing real code is
    left alone — that's either a legitimate part of the change or something
    the diff review is supposed to catch, not something to silently reverse.
    And a comment the model *reworded* shows up as a "replace" opcode, not a
    "delete" (nothing to restore against), which is deliberate: the rule
    book asks the model to update stale comment wording in place rather than
    delete it, and this must not fight that by restoring the old wording
    over the new.
    """
    if not rel_path.endswith(".py"):
        return content
    source_path = REPO_ROOT / rel_path
    if not source_path.exists():
        return content
    original_lines = source_path.read_text(encoding="utf-8").splitlines(keepends=True)
    generated_lines = content.splitlines(keepends=True)

    matcher = difflib.SequenceMatcher(None, original_lines, generated_lines, autojunk=False)
    insertions: list[tuple[int, list[str]]] = []
    for tag, i1, i2, j1, _j2 in matcher.get_opcodes():
        if tag != "delete":
            continue
        deleted = original_lines[i1:i2]
        if not any(line.strip().startswith("#") for line in deleted):
            continue  # a run of nothing but blank lines is not a content loss
        if not all(line.strip() == "" or line.lstrip().startswith("#") for line in deleted):
            continue  # deleted real code alongside it — a real edit, not ours to reverse
        insertions.append((j1, deleted))

    if not insertions:
        return content
    for insert_at, lines in sorted(insertions, key=lambda pair: pair[0], reverse=True):
        generated_lines[insert_at:insert_at] = lines
    try:
        ast.parse("".join(generated_lines), filename=rel_path)
    except SyntaxError:
        # A restored comment landed somewhere that broke indentation-sensitive
        # syntax (e.g. inside a continued expression) — bail out rather than
        # hand back content worse than what was passed in.
        return content
    return "".join(generated_lines)


def _top_level_def_starts(tree: ast.Module) -> dict[str, int]:
    """name -> 1-indexed line of each top-level def/class in `tree`,
    including its decorator line(s) if any (ast puts `FunctionDef.lineno` on
    the `def` line itself, not the decorator, so the decorator line has to be
    found separately)."""
    starts: dict[str, int] = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            first_line = node.lineno
            if node.decorator_list:
                first_line = min(dec.lineno for dec in node.decorator_list)
            starts[node.name] = first_line
    return starts


def _blank_run_before(lines: list[str], lineno: int) -> tuple[int, int]:
    """(blank_line_count, index_of_preceding_non_blank_line) for the run of
    blank lines immediately above 1-indexed `lineno` in `lines`. The second
    element is -1 if `lineno` is the first line in the file or every line
    above it is blank."""
    idx = lineno - 1
    count = 0
    cursor = idx - 1
    while cursor >= 0 and lines[cursor].strip() == "":
        count += 1
        cursor -= 1
    return count, cursor


def _restore_top_level_blank_lines(rel_path: str, content: str) -> str:
    """Restore the exact blank-line count that preceded each top-level
    def/class in the original file, wherever a whole-file replacement
    collapsed it (this repo's `ruff.toml` and PEP 8 both call for two blank
    lines between top-level definitions; the model routinely flattens runs
    like that to one).

    Matched by name, the same discipline `_restore_body_docstrings` uses: a
    renamed or newly-added def has no original position to restore, so its
    spacing is left exactly as the model wrote it. Deliberately narrower than
    running a general formatter (`ruff format`) over the whole file — that
    also collapses unrelated multi-line expressions the CR never touched
    (comprehensions, ternaries, wrapped calls) into a diff the reviewer has
    to puzzle over. This only ever rewrites the blank-line run immediately
    above a matched def/class; nothing else in the file is touched.
    """
    if not rel_path.endswith(".py"):
        return content
    source_path = REPO_ROOT / rel_path
    if not source_path.exists():
        return content
    try:
        original = source_path.read_text(encoding="utf-8")
        original_tree = ast.parse(original, filename=rel_path)
        generated_tree = ast.parse(content, filename=rel_path)
    except (SyntaxError, ValueError):
        # Invalid Python is _validate_content's problem to report, not ours.
        return content

    original_lines = original.splitlines(keepends=True)
    generated_lines = content.splitlines(keepends=True)
    original_starts = _top_level_def_starts(original_tree)
    generated_starts = _top_level_def_starts(generated_tree)

    # Collected then applied bottom-up (by generated line number) so an
    # earlier edit never shifts the line numbers still to be processed.
    fixes: list[tuple[int, int, int]] = []  # (preceding_line_idx, def_idx, desired_blanks)
    for name, orig_lineno in original_starts.items():
        gen_lineno = generated_starts.get(name)
        if gen_lineno is None:
            continue
        desired, orig_preceding = _blank_run_before(original_lines, orig_lineno)
        if orig_preceding < 0:
            continue  # nothing preceded it in the original either
        actual, gen_preceding = _blank_run_before(generated_lines, gen_lineno)
        if gen_preceding < 0 or actual == desired:
            continue
        fixes.append((gen_preceding, gen_lineno - 1, desired))

    if not fixes:
        return content
    for preceding_idx, def_idx, desired in sorted(fixes, key=lambda f: f[0], reverse=True):
        generated_lines[preceding_idx + 1 : def_idx] = ["\n"] * desired
    return "".join(generated_lines)


def _repair_generated_content(rel_path: str, content: str) -> str:
    """Chain of deterministic, non-LLM repairs applied to every generated
    file before it's staged or written — each undoes one specific thing
    whole-file replacement is known to drop: the module docstring, function
    docstrings, other dropped comment lines, and top-level blank-line
    spacing, in that order (each downstream repair re-parses the file fresh,
    so earlier line-count changes are always accounted for)."""
    content = _restore_module_docstring(rel_path, content)
    content = _restore_body_docstrings(rel_path, content)
    content = _restore_dropped_comment_lines(rel_path, content)
    content = _restore_top_level_blank_lines(rel_path, content)
    return content


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
        target.write_text(_repair_generated_content(rel_path, content), encoding="utf-8")
    return staged_dir


def _compute_diff(staged_dir: Path, files: dict[str, str]) -> str:
    """Unified diff of the staged proposal against the current repo, with no
    side effects. Split out from `_write_diff` so the revise prompt can show
    the model what it actually changed without writing a diff.patch."""
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
    return "".join(diff_parts)


def _write_diff(staged_dir: Path, files: dict[str, str]) -> str:
    diff_text = _compute_diff(staged_dir, files)
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
