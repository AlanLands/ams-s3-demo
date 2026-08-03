"""Live S3 test generation for the plan-tier-upgrade change.

The prompt/validation below is US-2026-041-specific, same caveat as
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
CACHE_KEY = targets.MOCKAPP_TIER_UPGRADE.stream_cache_key("testgen")
ALLOWLIST: tuple[str, ...] = targets.MOCKAPP_TIER_UPGRADE.testgen_allowlist
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
    story_text: str,
    *,
    target: Target | None = None,
    scenarios: list[dict] | None = None,
) -> TestgenResult:
    """Generate the target's test file.

    `scenarios` is the tester-approved plan (see s3_enhancement/scenarios.py).
    When supplied it is appended to the prompt, so a live or recording run
    writes the suite against the reviewed list rather than against the user story
    alone. It intentionally does not enter the cache key: the demo's streamed
    caches are keyed by literal (see targets.Target.stream_cache_key), so in
    replay mode the recorded suite is served whatever the plan says — the
    console is explicit about that rather than implying otherwise.
    """
    target = target or targets.get_target(None)
    if os.environ.get("LLM_MODE", "replay").lower() == "replay":
        return _generate_tests_once(
            tier_name, story_text, target=target, used_replay=True, scenarios=scenarios
        )
    try:
        return _generate_tests_once(
            tier_name, story_text, target=target, used_replay=False, scenarios=scenarios
        )
    except LLMError:
        with _temporary_env("LLM_MODE", "replay"):
            return _generate_tests_once(
                tier_name, story_text, target=target, used_replay=True, scenarios=scenarios
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
    story_text: str,
    *,
    target: Target,
    used_replay: bool,
    scenarios: list[dict] | None = None,
) -> TestgenResult:
    if target.cache_namespace == targets.MOCKAPP_AMENDMENT_FIELD_ADD.cache_namespace:
        prompt = build_amendment_prompt(story_text, target=target)
    elif target.cache_namespace == targets.CLAIMSPORTAL_CLAIMS_DEDUCTIBLE.cache_namespace:
        prompt = build_spring_prompt(story_text, target=target)
    elif target.cache_namespace == targets.ENROLDIRECT_PROSPECT_ACCESS.cache_namespace:
        prompt = build_enroldirect_prompt(story_text, target=target)
    else:
        prompt = build_prompt(tier_name, story_text)
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


def build_prompt(tier_name: str, story_text: str) -> str:
    mode = os.environ.get("LLM_MODE", "replay").lower()
    record_note = ""
    top_tier_literal = tier_name
    if mode == "record":
        top_tier_literal = "{{TIER_NAME}}"
        record_note = (
            "\nThe user story contains a placeholder token {{TIER_NAME}}. Reproduce it "
            "verbatim in generated test assertions; do not invent a concrete tier name."
        )

    reference = """Tests should cover:
- default tier is Standard after reseed
- upgrade to Premium recalculates the contribution and persists
- two-tier upgrade reaches the top tier and stays mathematically consistent
- unknown tier using "NotATier", downgrade, same-tier, and unknown policy raise ValueError
- PLAN_TIERS ordering is exactly ["Standard", "Premium", top tier]
"""

    context_files = []
    for rel_path in ("repos/policycore/core/models.py", "repos/policycore/core/db.py", "repos/policycore/core/seed.py"):
        path = REPO_ROOT / rel_path
        content = path.read_text(encoding="utf-8") if path.exists() else ""
        context_files.append(f"--- {rel_path} ---\n{content}")

    return f"""User story:
{story_text}
{record_note}

Audience-selected top tier name: {tier_name}
Top tier literal to assert in the generated tests: {top_tier_literal}

Current generated app files are already applied. Generate only this test file:
tests/test_s3_tier_upgrade.py

{reference}

Exact API to test — this is a fixed, known contract, do not guess field names,
do not write fallback/try-except import chains, and do not treat a Policy as a
dict:
{chr(10).join(context_files)}

`repos.policycore.core.tiers` exposes `PLAN_TIERS: list[str]`,
`TIER_MULTIPLIERS: dict[str, float]`, and
`upgrade_tier(policy_number: str, new_tier: str) -> Policy` (raises
`ValueError` on unknown tier / downgrade / same-tier / unknown policy).
The recalculated contribution is rounded to 2 decimals — expected values must
be computed as `round(contribution / old_multiplier * new_multiplier, 2)`, never
compared against an unrounded float.
`repos.policycore.core.db.get_policy(policy_number: str) -> Policy | None` and
`list_policies() -> list[Policy]` return `Policy` dataclass instances — access
fields with plain attribute access (`policy.plan_tier`, `policy.contribution`,
`policy.policy_number`), never dict-style `policy["..."]` or `.get(...)`.
`repos.policycore.core.seed.reseed() -> None` reseeds known synthetic policies
(e.g. "POL-10001") at plan_tier="Standard" — call it directly by that name
in an autouse fixture, no aliasing needed. An unknown policy number for the
"unknown policy" test should be an unmistakably invalid string like
"POL-99999", not an integer.

Return structured JSON only with this exact shape:
{{
  "files": [
    {{"path": "tests/test_s3_tier_upgrade.py", "content": "<complete replacement>"}}
  ]
}}

Use pytest, reseed the mock app database before each test via an autouse
fixture, and import directly from repos.policycore.core.tiers, repos.policycore.core.db, and
repos.policycore.core.seed using the exact names given above. The test file should be
deterministic and have no LLM calls or network access."""


def build_amendment_prompt(story_text: str, *, target: Target) -> str:
    """Prompt for US-2026-042's generated test file — no audience-picked
    placeholder, unlike the tier-upgrade user story's {{TIER_NAME}}."""
    test_path = target.testgen_allowlist[0]

    reference = """Tests should cover:
- submitting an amendment request with no priority argument defaults to "Standard"
- submitting an amendment request with priority="Urgent" persists "Urgent"
- the persisted amendment round-trips through list_amendments() with the
  chosen priority
- existing fields (amendment_type, requested_change, effective_date,
  contact_phone, contact_email) are unaffected by the new field
"""

    context_files = []
    for rel_path in (
        "repos/policycore/core/models.py",
        "repos/policycore/core/db.py",
        "repos/policycore/core/amendments.py",
        "repos/policycore/core/seed.py",
    ):
        path = REPO_ROOT / rel_path
        content = path.read_text(encoding="utf-8") if path.exists() else ""
        context_files.append(f"--- {rel_path} ---\n{content}")

    return f"""User story:
{story_text}

Current generated app files are already applied. Generate only this test file:
{test_path}

{reference}

Exact API to test — this is a fixed, known contract, do not guess field names,
do not write fallback/try-except import chains, and do not treat an
Amendment as a dict:
{chr(10).join(context_files)}

`repos.policycore.core.amendments.submit_amendment(policy_number: str,
amendment_type: str, requested_change: str, effective_date: str,
contact_phone: str, contact_email: str, priority: str = "Standard") ->
Amendment` is the only function that creates an amendment.
`repos.policycore.core.db.list_amendments(policy_number: str) -> list[Amendment]`
returns `Amendment` dataclass instances — access fields with plain
attribute access (`amendment.priority`), never dict-style access.
`repos.policycore.core.seed.reseed() -> None` reseeds known synthetic policies (e.g.
"POL-10001") — call it directly by that name in an autouse fixture, no
aliasing needed.

Return structured JSON only with this exact shape:
{{
  "files": [
    {{"path": "{test_path}", "content": "<complete replacement>"}}
  ]
}}

Use pytest, reseed the mock app database before each test via an autouse
fixture, and import directly from repos.policycore.core.amendments, repos.policycore.core.db,
and repos.policycore.core.seed using the exact names given above. The test file should
be deterministic and have no LLM calls or network access."""


def build_spring_prompt(story_text: str, *, target: Target) -> str:
    """Prompt for US-2026-043's generated pytest suite — a plain unit test of
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

    return f"""User story:
{story_text}

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
repos.claimsportal.claims_service.claim_rules. Plain unit tests of claim_rules
only: no FastAPI TestClient, no server startup, no mocking, no network. Use
modern built-in generics for any type hint (never `typing.Optional` etc.) and
keep every line at 100 characters or fewer. The test file must be
deterministic."""


def build_enroldirect_prompt(story_text: str, *, target: Target) -> str:
    """Prompt for US-2026-045's generated pytest suite.

    Plain unit tests of the gate, built from `Applicant`/`GroupContract`
    literals rather than the seeded directory — no HTTP, no app startup, so it
    stays fast and deterministic and does not double up on
    `tests/test_regression_enroldirect.py`, which already covers the seeded
    book through the API. This suite tests the change; that one tests what the
    change must not break.
    """
    test_path = target.testgen_allowlist[0]

    reference = """Tests should cover:
- effective_category("PROSPECT") is the value of PROSPECT_POLICY, and
  effective_category is the identity for "MEMBER" and "GUEST"
- preference_for_category("PROSPECT") resolves through PROSPECT_POLICY. Write
  it exactly as:
      expected = MEMBER_ACCESS if PROSPECT_POLICY == TREAT_AS_MEMBER else GUEST_ACCESS
      assert preference_for_category(PROSPECT) == expected
  PROSPECT_POLICY is module-level configuration: READ it, never reassign it.
  Do not use `global`, monkeypatch, setattr, or any fixture that changes it —
  a test that mutates it is testing a setting the running app does not have
- preference_for_category is unchanged for "MEMBER" and "GUEST", and still
  returns None for an unrecognised category
- a prospect on an ACTIVE contract enabling the resolved preference is granted,
  and the decision's authorisingPreference is that preference
- a prospect on an ACTIVE contract that enables only the OTHER preference is
  denied, with requiredPreference set and authorisingPreference None
- a prospect on a LAPSED contract is denied at the contract gate even when the
  contract enables both preferences — gate order, and it must not depend on
  the policy
- prospectPolicyApplied is PROSPECT_POLICY on a prospect's decision and None on
  a member's and a guest's
"""

    context_files = []
    context_paths = [
        rel_path
        for rel_path in target.codegen_allowlist
        if rel_path.endswith(("applicants.py", "eligibility.py"))
    ]
    for rel_path in context_paths:
        path = REPO_ROOT / rel_path
        content = path.read_text(encoding="utf-8") if path.exists() else ""
        context_files.append(f"--- {rel_path} ---\n{content}")

    return f"""User story:
{story_text}

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

Use plain pytest functions. Start the file with exactly these four imports,
and add nothing else — every name the tests below need is in them:

from repos.enroldirect.applicants import (
    GUEST, MEMBER, PROSPECT, PROSPECT_POLICY, TREAT_AS_GUEST, TREAT_AS_MEMBER, Applicant
)
from repos.enroldirect.directory import GroupContract
from repos.enroldirect.eligibility import (
    ACTIVE, check_eligibility, effective_category, preference_for_category
)
from repos.enroldirect.preferences import GUEST_ACCESS, MEMBER_ACCESS

Construct real `Applicant` and `GroupContract` instances inline in each test.
Do NOT define a mock or stub contract class, and do NOT use
`directory.CONTRACTS` or `directory.APPLICANTS` — the class is the contract,
the seeded book is not, so a change to the seed cannot break this suite.
`GroupContract(contractNumber=..., sponsorName=..., status=...,
enabledPreferences=(...))` takes a TUPLE of preferences. `Applicant` is
positional: (applicantId, fullName, contractNumber, category, hasActiveBenefit),
and its `__post_init__` rejects a MEMBER with no active benefit and a PROSPECT
holding one — construct prospects with hasActiveBenefit=False and members with
True. An applicant's contractNumber must match the contract's or the gate
raises.
Assert against the imported constants (MEMBER_ACCESS, GUEST_ACCESS, ACTIVE),
never against a string literal of the constant's own name.
No FastAPI TestClient, no server startup, no mocking, no network. Use modern
built-in generics for any type hint (never `typing.Optional` etc.) and keep
every line at 100 characters or fewer. The test file must be deterministic.

Write every import as valid Python. A multi-name import that needs wrapping
must use parentheses — `from m import (A, B, C)` across lines, never
`from m import A, B,` with a trailing comma and no parentheses, which is a
SyntaxError. Prefer one unwrapped import per module where the names fit on a
single line under 100 characters."""


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
