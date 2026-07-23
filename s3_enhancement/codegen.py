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
    naive_input_tokens_estimate: int = 0


def generate_change(
    tier_name: str, cr_text: str, *, target: Target | None = None
) -> CodegenResult:
    """Generate, validate, stage, diff, and apply the target's file replacements."""
    target = target or targets.get_target(None)
    if os.environ.get("LLM_MODE", "replay").lower() == "replay":
        return _generate_change_once(tier_name, cr_text, target=target, used_replay=True)
    try:
        return _generate_change_once(tier_name, cr_text, target=target, used_replay=False)
    except LLMError:
        with _temporary_env("LLM_MODE", "replay"):
            return _generate_change_once(tier_name, cr_text, target=target, used_replay=True)


def _generate_change_once(
    tier_name: str, cr_text: str, *, target: Target, used_replay: bool
) -> CodegenResult:
    all_files = relevance.discover_files_for_target(target, cr_text)
    selection = relevance.select_relevant_files(
        cr_text, all_files, core_files=target.core_files
    )
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
    # substitute in every mode so record runs never apply placeholder-bearing
    # files to the working tree (the replay cache itself is written raw, inside
    # stream_complete, before this line). A live response has no token — no-op.
    response = "".join(chunks).replace("{{TIER_NAME}}", tier_name)
    files = _parse_files_response(response)
    _validate_file_set(files, selection)
    staged_dir = _stage_files(files)
    diff_text = _write_diff(staged_dir, files)
    _apply_staged_files(staged_dir, files)
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
        naive_input_tokens_estimate=sum(
            relevance.estimate_tokens(content) for content in all_files.values()
        ),
    )


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
                {"path": rel_path, "content": "<complete replacement>"}
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


def _parse_files_response(response: str) -> dict[str, str]:
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
    for item in data["files"]:
        if not isinstance(item, dict):
            raise LLMError("S3 codegen files entries must be objects")
        path = item.get("path")
        content = item.get("content")
        if not isinstance(path, str) or not isinstance(content, str):
            raise LLMError("S3 codegen file entries need string path and content")
        files[path] = content
    return files


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


def _stage_files(files: dict[str, str]) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    staged_dir = OUT_ROOT / stamp / "staged"
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
