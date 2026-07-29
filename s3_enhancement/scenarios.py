"""Test scenarios drafted from a CR, before any test code exists.

The beat this fills: S3 used to go straight from change request to a pytest
file. Every QA function this demo is shown to writes scenarios first — a
numbered plan of what will be checked, in prose a business analyst can sign
off, traced to the acceptance criteria it came from — and only then automates
them. Skipping that step is what makes generated tests feel like a black box:
the reviewer's only artifact is code, so the only available review is a code
review, which is the wrong review for "did we understand the requirement?".

What this module deliberately does *not* do:

* It does not invent acceptance criteria. Those are parsed out of the CR
  (`acceptance.py`); the model's job is to propose coverage *of* them, and
  every scenario must cite the criterion it serves. A scenario citing an
  unknown criterion is a validation error, not a warning — an untraceable
  scenario is exactly the thing this beat exists to prevent.
* It does not decide what gets automated. The drafted list is a proposal the
  tester edits, deletes from, and adds to before it means anything; the
  approved list is what downstream beats consume.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field

from common.llm import LLMError, complete
from s3_enhancement import targets
from s3_enhancement.acceptance import Criterion, parse_acceptance_criteria
from s3_enhancement.targets import Target

SYSTEM_PROMPT = (
    "You are a senior QA analyst writing a test plan for a small change "
    "request. Return structured JSON only. No markdown fences, no prose."
)

# The four categories a test analyst would recognise. "regression" is the
# interesting one: it marks a scenario that is satisfied by the app's existing
# suite rather than by anything the CR adds, which is how the traceability
# matrix knows to point that row at the regression run instead of at a
# generated test.
KINDS = ("positive", "negative", "boundary", "regression")

MAX_SCENARIOS = 14
_SECRET_RE = re.compile(
    r"(sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----)"
)
_FORBIDDEN = ("real client", ".env", "api_key", "api key")


@dataclass(frozen=True)
class Scenario:
    """One planned check, in the shape a manual test case takes."""

    id: str
    title: str
    kind: str
    acceptance_criteria: tuple[str, ...]
    preconditions: str
    test_data: str
    steps: tuple[str, ...]
    expected: str

    def to_dict(self) -> dict:
        data = asdict(self)
        data["acceptance_criteria"] = list(self.acceptance_criteria)
        data["steps"] = list(self.steps)
        return data


@dataclass
class ScenarioDraft:
    scenarios: list[Scenario]
    criteria: list[Criterion]
    scoped_input_tokens: int | None = None
    scoped_output_tokens: int | None = None
    tokens_estimated: bool = False
    # Criteria no scenario cites. Computed here rather than in the UI so the
    # gap is part of the artifact — a plan that silently skips a requirement
    # should fail review, and it can only do that if it says so out loud.
    uncovered_criteria: list[str] = field(default_factory=list)


def scenario_from_dict(raw: dict) -> Scenario:
    """Rebuild a Scenario from JSON — the model's output and the tester's
    edited version come back through the same door, so both get the same
    coercion (and, at the callers, the same validation)."""
    steps = raw.get("steps") or []
    if isinstance(steps, str):
        steps = [steps]
    refs = raw.get("acceptance_criteria") or []
    if isinstance(refs, str):
        refs = [refs]
    return Scenario(
        id=str(raw.get("id", "")).strip(),
        title=str(raw.get("title", "")).strip(),
        kind=str(raw.get("kind", "")).strip().lower(),
        acceptance_criteria=tuple(str(ref).strip() for ref in refs if str(ref).strip()),
        preconditions=str(raw.get("preconditions", "")).strip(),
        test_data=str(raw.get("test_data", "")).strip(),
        steps=tuple(str(step).strip() for step in steps if str(step).strip()),
        expected=str(raw.get("expected", "")).strip(),
    )


def validate_scenarios(scenarios: list[Scenario], criteria: list[Criterion]) -> None:
    """Reject a scenario list that could not be reviewed or traced.

    Applied to the model's draft *and* to a tester-edited list arriving from
    the console — an edit that strips a scenario's expected result or points
    it at a criterion the CR doesn't contain is just as broken as a bad
    generation, and the API is the only place both paths meet.
    """
    if not scenarios:
        raise LLMError("Test scenario draft was empty.")
    if len(scenarios) > MAX_SCENARIOS:
        raise LLMError(
            f"Test scenario draft returned {len(scenarios)} scenarios; "
            f"the cap is {MAX_SCENARIOS}."
        )

    known = {criterion.id for criterion in criteria}
    seen: set[str] = set()
    for scenario in scenarios:
        if not scenario.id:
            raise LLMError("Every scenario needs an id.")
        if scenario.id in seen:
            raise LLMError(f"Duplicate scenario id {scenario.id!r}.")
        seen.add(scenario.id)
        if not scenario.title:
            raise LLMError(f"{scenario.id} has no title.")
        if scenario.kind not in KINDS:
            raise LLMError(
                f"{scenario.id} has kind {scenario.kind!r}; expected one of {list(KINDS)}."
            )
        if not scenario.expected:
            raise LLMError(f"{scenario.id} has no expected result.")
        if not scenario.steps:
            raise LLMError(f"{scenario.id} has no steps.")
        # Only enforced when the CR actually has criteria to trace to; an
        # ad-hoc ticket has none, and an untraceable plan is better than no
        # plan there.
        if known:
            if not scenario.acceptance_criteria:
                raise LLMError(f"{scenario.id} cites no acceptance criterion.")
            for ref in scenario.acceptance_criteria:
                if ref not in known:
                    raise LLMError(
                        f"{scenario.id} cites unknown acceptance criterion {ref!r}; "
                        f"this CR has {sorted(known)}."
                    )

        blob = " ".join(
            [scenario.title, scenario.preconditions, scenario.test_data, scenario.expected]
        ).lower()
        for forbidden in _FORBIDDEN:
            if forbidden in blob:
                raise LLMError(f"{scenario.id} contains forbidden string {forbidden!r}.")
        if _SECRET_RE.search(blob):
            raise LLMError(f"{scenario.id} contains secret-shaped content.")


def uncovered_criteria(scenarios: list[Scenario], criteria: list[Criterion]) -> list[str]:
    cited = {ref for scenario in scenarios for ref in scenario.acceptance_criteria}
    return [criterion.id for criterion in criteria if criterion.id not in cited]


def build_prompt(cr_text: str, criteria: list[Criterion], *, target: Target) -> str:
    criteria_block = (
        "\n".join(f"{criterion.id}: {criterion.text}" for criterion in criteria)
        or "(this ticket has no numbered acceptance criteria)"
    )
    language = "Java/Spring Boot" if target.language == "java" else "Python"
    return f"""Change request:
{cr_text}

Acceptance criteria, already extracted from the CR above — cite these ids
verbatim, and do not invent, renumber, merge or reword them:
{criteria_block}

Draft the test scenarios a QA analyst would write for this change, before any
test code is written. The application under test is {target.display_name}
({language}).

Rules:
- Cover every acceptance criterion listed above at least once. A criterion
  about existing behaviour being unaffected is covered by a scenario of kind
  "regression".
- Use test-design technique deliberately: include the boundary cases (values
  at, just below and just above any threshold or limit the CR names) and the
  negative cases (invalid, missing or out-of-range input), not just the happy
  path. Mark those with kind "boundary" and "negative" respectively.
- Prefer few, sharp scenarios over many overlapping ones. At most
  {MAX_SCENARIOS}.
- `test_data` must be concrete synthetic values (policy numbers, amounts,
  field values) for a fictional insurer, never real-looking personal data.
- `steps` are what a tester does, in order, in plain language — not code.
- `expected` is a single observable outcome, specific enough to fail on.

Return structured JSON only, with this exact shape:
{{
  "scenarios": [
    {{
      "id": "TS-01",
      "title": "short imperative summary",
      "kind": "positive|negative|boundary|regression",
      "acceptance_criteria": ["AC-1"],
      "preconditions": "state the system must be in first",
      "test_data": "concrete synthetic values used",
      "steps": ["first action", "second action"],
      "expected": "the single observable outcome"
    }}
  ]
}}"""


def _parse_response(response: str) -> list[Scenario]:
    text = response.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMError(
            f"Test scenario response was not valid JSON: {response[:200]!r}"
        ) from exc
    if not isinstance(data, dict) or not isinstance(data.get("scenarios"), list):
        raise LLMError("Test scenario response must be an object with a scenarios list")
    scenarios = []
    for raw in data["scenarios"]:
        if not isinstance(raw, dict):
            raise LLMError("Each scenario must be a JSON object")
        scenarios.append(scenario_from_dict(raw))
    return scenarios


def draft_scenarios(cr_text: str, *, target: Target | None = None) -> ScenarioDraft:
    """Draft the test plan for `cr_text`. Never writes to the working tree —
    this beat produces a document, not code."""
    target = target or targets.get_target(None)
    criteria = parse_acceptance_criteria(cr_text)
    prompt = build_prompt(cr_text, criteria, target=target)
    usage: dict = {}

    response = complete(
        prompt,
        system=SYSTEM_PROMPT,
        json_mode=True,
        cache_key=target.cache_key("test_scenarios"),
        retries=0 if os.environ.get("LLM_MODE", "replay").lower() == "replay" else 2,
        usage_out=usage,
    )
    scenarios = _parse_response(response)
    validate_scenarios(scenarios, criteria)
    return ScenarioDraft(
        scenarios=scenarios,
        criteria=criteria,
        scoped_input_tokens=usage.get("input_tokens"),
        scoped_output_tokens=usage.get("output_tokens"),
        tokens_estimated=bool(usage.get("estimated")),
        uncovered_criteria=uncovered_criteria(scenarios, criteria),
    )
