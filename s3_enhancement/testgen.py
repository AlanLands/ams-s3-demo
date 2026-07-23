"""Live S3 test generation for the coverage-upgrade change.

The prompt/validation below is CR-2026-041-specific, same caveat as
codegen.py — a second `Target` needs its own prompt/validator pair, not just a
registry entry. See s3_enhancement/targets.py.
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
from s3_enhancement import targets
from s3_enhancement.targets import Target

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_ROOT = REPO_ROOT / "s3_enhancement" / "out"
CACHE_KEY = targets.MOCKAPP_COVERAGE_UPGRADE.stream_cache_key("testgen")
ALLOWLIST: tuple[str, ...] = targets.MOCKAPP_COVERAGE_UPGRADE.testgen_allowlist
SYSTEM_PROMPT = (
    "You are an AI pair programmer for a live AMS demo. Return structured JSON "
    "only. Do not include markdown fences, prose, or diffs."
)
_SECRET_RE = re.compile(
    r"(sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----)"
)


@dataclass
class TestgenResult:
    tier_name: str
    diff_text: str
    files_changed: list[str]
    used_replay: bool
    stream_text_generator: Iterator[str] | None
    scoped_input_tokens: int | None = None
    scoped_output_tokens: int | None = None


def generate_tests(
    tier_name: str, cr_text: str, *, target: Target | None = None
) -> TestgenResult:
    target = target or targets.get_target(None)
    if os.environ.get("LLM_MODE", "replay").lower() == "replay":
        return _generate_tests_once(tier_name, cr_text, target=target, used_replay=True)
    try:
        return _generate_tests_once(tier_name, cr_text, target=target, used_replay=False)
    except LLMError:
        with _temporary_env("LLM_MODE", "replay"):
            return _generate_tests_once(tier_name, cr_text, target=target, used_replay=True)


def _generate_tests_once(
    tier_name: str, cr_text: str, *, target: Target, used_replay: bool
) -> TestgenResult:
    prompt = build_prompt(tier_name, cr_text)
    usage: dict = {}
    substitutions = {"{{TIER_NAME}}": tier_name} if used_replay else None
    chunks: list[str] = []
    try:
        for chunk in stream_complete(
            prompt,
            system=SYSTEM_PROMPT,
            json_mode=True,
            cache_key=target.stream_cache_key("testgen"),
            retries=0,
            replay_substitutions=substitutions,
            chunk_delay=-1,
            usage_out=usage,
        ):
            chunks.append(chunk)
    except LLMError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise LLMError(f"S3 testgen stream failed: {exc}") from exc

    # Same reasoning as codegen.py: substitute in every mode so record runs
    # never apply a placeholder-bearing test file to the working tree.
    response = "".join(chunks).replace("{{TIER_NAME}}", tier_name)
    files = _parse_files_response(response)
    allowlist = target.testgen_allowlist
    _validate_file_set(files, allowlist=allowlist)
    staged_dir = _stage_files(files)
    diff_text = _write_diff(staged_dir, allowlist=allowlist)
    _apply_staged_files(staged_dir, allowlist=allowlist)
    return TestgenResult(
        tier_name=tier_name,
        diff_text=diff_text,
        files_changed=list(allowlist),
        used_replay=used_replay,
        stream_text_generator=iter(chunks),
        scoped_input_tokens=usage.get("input_tokens"),
        scoped_output_tokens=usage.get("output_tokens"),
    )


def build_prompt(tier_name: str, cr_text: str) -> str:
    mode = os.environ.get("LLM_MODE", "replay").lower()
    record_note = ""
    top_tier_literal = tier_name
    if mode == "record":
        top_tier_literal = "{{TIER_NAME}}"
        record_note = (
            "\nThe CR contains a placeholder token {{TIER_NAME}}. Reproduce it "
            "verbatim in generated test assertions; do not invent a concrete tier name."
        )

    reference = """Tests should cover:
- default tier is Standard after reseed
- upgrade to Premium recalculates premium and persists
- two-tier upgrade reaches the top tier and stays mathematically consistent
- unknown tier using "NotATier", downgrade, same-tier, and unknown policy raise ValueError
- COVERAGE_TIERS ordering is exactly ["Standard", "Premium", top tier]
"""

    context_files = []
    for rel_path in ("mockapp/core/models.py", "mockapp/core/db.py", "mockapp/core/seed.py"):
        path = REPO_ROOT / rel_path
        content = path.read_text(encoding="utf-8") if path.exists() else ""
        context_files.append(f"--- {rel_path} ---\n{content}")

    return f"""Change request:
{cr_text}
{record_note}

Audience-selected top tier name: {tier_name}
Top tier literal to assert in the generated tests: {top_tier_literal}

Current generated app files are already applied. Generate only this test file:
tests/test_s3_coverage_upgrade.py

{reference}

Exact API to test — this is a fixed, known contract, do not guess field names,
do not write fallback/try-except import chains, and do not treat a Policy as a
dict:
{chr(10).join(context_files)}

`mockapp.core.coverage` exposes `COVERAGE_TIERS: list[str]`,
`TIER_MULTIPLIERS: dict[str, float]`, and
`upgrade_coverage(policy_number: str, new_tier: str) -> Policy` (raises
`ValueError` on unknown tier / downgrade / same-tier / unknown policy).
The recalculated premium is rounded to 2 decimals — expected values must be
computed as `round(premium / old_multiplier * new_multiplier, 2)`, never
compared against an unrounded float.
`mockapp.core.db.get_policy(policy_number: str) -> Policy | None` and
`list_policies() -> list[Policy]` return `Policy` dataclass instances — access
fields with plain attribute access (`policy.coverage_tier`, `policy.premium`,
`policy.policy_number`), never dict-style `policy["..."]` or `.get(...)`.
`mockapp.core.seed.reseed() -> None` reseeds known synthetic policies
(e.g. "POL-10001") at coverage_tier="Standard" — call it directly by that name
in an autouse fixture, no aliasing needed. An unknown policy number for the
"unknown policy" test should be an unmistakably invalid string like
"POL-99999", not an integer.

Return structured JSON only with this exact shape:
{{
  "files": [
    {{"path": "tests/test_s3_coverage_upgrade.py", "content": "<complete replacement>"}}
  ]
}}

Use pytest, reseed the mock app database before each test via an autouse
fixture, and import directly from mockapp.core.coverage, mockapp.core.db, and
mockapp.core.seed using the exact names given above. The test file should be
deterministic and have no LLM calls or network access."""


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
        raise LLMError(f"S3 testgen response was not valid JSON: {response[:200]!r}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("files"), list):
        raise LLMError("S3 testgen response must be an object with a files list")

    files: dict[str, str] = {}
    for item in data["files"]:
        if not isinstance(item, dict):
            raise LLMError("S3 testgen files entries must be objects")
        path = item.get("path")
        content = item.get("content")
        if not isinstance(path, str) or not isinstance(content, str):
            raise LLMError("S3 testgen file entries need string path and content")
        files[path] = content
    return files


def _validate_file_set(files: dict[str, str], *, allowlist: tuple[str, ...] = ALLOWLIST) -> None:
    if set(files) != set(allowlist):
        raise LLMError(
            "S3 testgen returned unexpected file set: "
            f"expected {sorted(allowlist)}, got {sorted(files)}"
        )
    content = files[allowlist[0]]
    try:
        ast.parse(content, filename=allowlist[0])
    except SyntaxError as exc:
        raise LLMError(f"S3 generated invalid Python for {allowlist[0]}: {exc}") from exc
    lowered = content.lower()
    for forbidden in ("real client", ".env", "api_key", "api key", "secret"):
        if forbidden in lowered:
            raise LLMError(f"S3 generated forbidden string {forbidden!r} in tests")
    if _SECRET_RE.search(content):
        raise LLMError("S3 generated secret-shaped content in tests")


def _stage_files(files: dict[str, str]) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    staged_dir = OUT_ROOT / stamp / "staged"
    for rel_path, content in files.items():
        target = staged_dir / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return staged_dir


def _write_diff(staged_dir: Path, *, allowlist: tuple[str, ...] = ALLOWLIST) -> str:
    rel_path = allowlist[0]
    source_path = REPO_ROOT / rel_path
    staged_path = staged_dir / rel_path
    old = source_path.read_text(encoding="utf-8").splitlines(keepends=True) \
        if source_path.exists() else []
    new = staged_path.read_text(encoding="utf-8").splitlines(keepends=True)
    diff_text = "".join(
        difflib.unified_diff(old, new, fromfile=f"a/{rel_path}", tofile=f"b/{rel_path}")
    )
    diff_path = staged_dir.parent / "diff.patch"
    diff_path.write_text(diff_text, encoding="utf-8")
    return diff_text


def _apply_staged_files(staged_dir: Path, *, allowlist: tuple[str, ...] = ALLOWLIST) -> None:
    for rel_path in allowlist:
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
