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
    tokens_estimated: bool = False


def generate_tests(
    tier_name: str,
    cr_text: str,
    *,
    target: Target | None = None,
    scenarios: list[dict] | None = None,
) -> TestgenResult:
    """Generate the target's test file.

    `scenarios` is the tester-approved plan (see s3_enhancement/scenarios.py).
    When supplied it is appended to the prompt, so a live or recording run
    writes the suite against the reviewed list rather than against the CR
    alone. It intentionally does not enter the cache key: the demo's streamed
    caches are keyed by literal (see targets.Target.stream_cache_key), so in
    replay mode the recorded suite is served whatever the plan says — the
    console is explicit about that rather than implying otherwise.
    """
    target = target or targets.get_target(None)
    if os.environ.get("LLM_MODE", "replay").lower() == "replay":
        return _generate_tests_once(
            tier_name, cr_text, target=target, used_replay=True, scenarios=scenarios
        )
    try:
        return _generate_tests_once(
            tier_name, cr_text, target=target, used_replay=False, scenarios=scenarios
        )
    except LLMError:
        with _temporary_env("LLM_MODE", "replay"):
            return _generate_tests_once(
                tier_name, cr_text, target=target, used_replay=True, scenarios=scenarios
            )


def _format_scenarios(scenarios: list[dict] | None) -> str:
    """Render the approved plan as prompt context. Defensive about shape: this
    data round-tripped through the browser and a tester's edits, so a missing
    key must degrade the prompt, never raise."""
    if not scenarios:
        return ""
    lines = []
    for scenario in scenarios:
        refs = scenario.get("acceptance_criteria") or []
        ref_text = f" [{', '.join(str(ref) for ref in refs)}]" if refs else ""
        lines.append(
            f"- {scenario.get('id', '?')} ({scenario.get('kind', 'unspecified')})"
            f"{ref_text}: {scenario.get('title', '')}\n"
            f"    expected: {scenario.get('expected', '')}"
        )
    return (
        "\n\nThe tester has reviewed and approved this test plan. Write one "
        "test per scenario below, in this order, and name each test so the "
        "scenario it implements is recognisable:\n" + "\n".join(lines)
    )


def _generate_tests_once(
    tier_name: str,
    cr_text: str,
    *,
    target: Target,
    used_replay: bool,
    scenarios: list[dict] | None = None,
) -> TestgenResult:
    if target.cache_namespace == targets.MOCKAPP_ENDORSEMENT_FIELD_ADD.cache_namespace:
        prompt = build_endorsement_prompt(cr_text, target=target)
    elif target.cache_namespace == targets.SPRINGDEMO_CLAIMS_DEDUCTIBLE.cache_namespace:
        prompt = build_spring_prompt(cr_text, target=target)
    else:
        prompt = build_prompt(tier_name, cr_text)
    prompt += _format_scenarios(scenarios)
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
        tokens_estimated=bool(usage.get("estimated")),
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
    for rel_path in ("apps/policycore/core/models.py", "apps/policycore/core/db.py", "apps/policycore/core/seed.py"):
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

`apps.policycore.core.coverage` exposes `COVERAGE_TIERS: list[str]`,
`TIER_MULTIPLIERS: dict[str, float]`, and
`upgrade_coverage(policy_number: str, new_tier: str) -> Policy` (raises
`ValueError` on unknown tier / downgrade / same-tier / unknown policy).
The recalculated premium is rounded to 2 decimals — expected values must be
computed as `round(premium / old_multiplier * new_multiplier, 2)`, never
compared against an unrounded float.
`apps.policycore.core.db.get_policy(policy_number: str) -> Policy | None` and
`list_policies() -> list[Policy]` return `Policy` dataclass instances — access
fields with plain attribute access (`policy.coverage_tier`, `policy.premium`,
`policy.policy_number`), never dict-style `policy["..."]` or `.get(...)`.
`apps.policycore.core.seed.reseed() -> None` reseeds known synthetic policies
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
fixture, and import directly from apps.policycore.core.coverage, apps.policycore.core.db, and
apps.policycore.core.seed using the exact names given above. The test file should be
deterministic and have no LLM calls or network access."""


def build_endorsement_prompt(cr_text: str, *, target: Target) -> str:
    """Prompt for CR-2026-042's generated test file — no audience-picked
    placeholder, unlike the coverage-upgrade CR's {{TIER_NAME}}."""
    test_path = target.testgen_allowlist[0]

    reference = """Tests should cover:
- submitting an endorsement request with no priority argument defaults to "Standard"
- submitting an endorsement request with priority="Urgent" persists "Urgent"
- the persisted endorsement round-trips through list_endorsements() with the
  chosen priority
- existing fields (endorsement_type, requested_change, effective_date,
  contact_phone, contact_email) are unaffected by the new field
"""

    context_files = []
    for rel_path in (
        "apps/policycore/core/models.py",
        "apps/policycore/core/db.py",
        "apps/policycore/core/endorsements.py",
        "apps/policycore/core/seed.py",
    ):
        path = REPO_ROOT / rel_path
        content = path.read_text(encoding="utf-8") if path.exists() else ""
        context_files.append(f"--- {rel_path} ---\n{content}")

    return f"""Change request:
{cr_text}

Current generated app files are already applied. Generate only this test file:
{test_path}

{reference}

Exact API to test — this is a fixed, known contract, do not guess field names,
do not write fallback/try-except import chains, and do not treat an
Endorsement as a dict:
{chr(10).join(context_files)}

`apps.policycore.core.endorsements.submit_endorsement(policy_number: str,
endorsement_type: str, requested_change: str, effective_date: str,
contact_phone: str, contact_email: str, priority: str = "Standard") ->
Endorsement` is the only function that creates an endorsement.
`apps.policycore.core.db.list_endorsements(policy_number: str) -> list[Endorsement]`
returns `Endorsement` dataclass instances — access fields with plain
attribute access (`endorsement.priority`), never dict-style access.
`apps.policycore.core.seed.reseed() -> None` reseeds known synthetic policies (e.g.
"POL-10001") — call it directly by that name in an autouse fixture, no
aliasing needed.

Return structured JSON only with this exact shape:
{{
  "files": [
    {{"path": "{test_path}", "content": "<complete replacement>"}}
  ]
}}

Use pytest, reseed the mock app database before each test via an autouse
fixture, and import directly from apps.policycore.core.endorsements, apps.policycore.core.db,
and apps.policycore.core.seed using the exact names given above. The test file should
be deterministic and have no LLM calls or network access."""


def build_spring_prompt(cr_text: str, *, target: Target) -> str:
    """Prompt for CR-2026-043's generated pytest suite — a plain unit test of
    the claim_rules contract, no HTTP/app startup, so it stays fast and
    deterministic. Name kept from this target's Java-era history (see
    CLAUDE.md); the source is Python since the 2026-07-30 rewrite."""
    test_path = target.testgen_allowlist[0]

    reference = """Tests should cover:
- a claim strictly above the deductible and within the limit on an ACTIVE
  policy is "ACCEPTED"
- a claim at exactly the deductible, and one below it, is
  "REJECTED_BELOW_DEDUCTIBLE"
- a claim above the coverage limit is "REJECTED_OVER_LIMIT" even when it is
  also above the deductible
- any non-ACTIVE status (e.g. "LAPSED") is "REJECTED_POLICY_LAPSED",
  taking precedence over both amount checks
- payable(amount, deductible) is amount minus deductible, and never negative
  (a deductible larger than the amount floors at zero)
"""

    context_files = []
    context_paths = [
        rel_path
        for rel_path in target.codegen_allowlist
        if rel_path.endswith(("claim_rules.py", "claim.py"))
    ]
    for rel_path in context_paths:
        path = REPO_ROOT / rel_path
        content = path.read_text(encoding="utf-8") if path.exists() else ""
        context_files.append(f"--- {rel_path} ---\n{content}")

    return f"""Change request:
{cr_text}

Current generated app files are already applied. Generate only this test file:
{test_path}

{reference}

Exact API to test — this is a fixed, known contract, do not guess names and
do not add fallback logic:
{chr(10).join(context_files)}

Return structured JSON only with this exact shape:
{{
  "files": [
    {{"path": "{test_path}", "content": "<complete replacement>"}}
  ]
}}

Use plain pytest functions importing `decide`/`payable` directly from
apps.claimsportal.claims_service.claim_rules. Plain unit tests of claim_rules
only: no FastAPI TestClient, no server startup, no mocking, no network. Use
modern built-in generics for any type hint (never `typing.Optional` etc.) and
keep every line at 100 characters or fewer. The test file must be
deterministic."""


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
