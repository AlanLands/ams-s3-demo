"""Verifies s3_enhancement/scenarios.py -- the validation that stands between
a drafted (or tester-edited) test plan and everything downstream of it."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from common.llm import LLMError
from s3_enhancement import scenarios as scenarios_mod
from s3_enhancement.acceptance import Criterion
from s3_enhancement.scenarios import (
    MAX_SCENARIOS,
    draft_scenarios,
    scenario_from_dict,
    uncovered_criteria,
    validate_scenarios,
)
from s3_enhancement.targets import MOCKAPP_AMENDMENT_FIELD_ADD

CRITERIA = [
    Criterion("AC-1", "The form has a Priority field."),
    Criterion("AC-2", "Existing flows are unaffected."),
]


def _raw(**overrides) -> dict:
    base = {
        "id": "TS-01",
        "title": "Default priority is Standard",
        "kind": "positive",
        "acceptance_criteria": ["AC-1"],
        "preconditions": "A seeded policy exists",
        "test_data": "POL-10001",
        "steps": ["Open the form", "Submit without touching priority"],
        "expected": "The stored amendment has priority Standard",
    }
    base.update(overrides)
    return base


def test_accepts_a_well_formed_plan():
    validate_scenarios([scenario_from_dict(_raw())], CRITERIA)


def test_rejects_an_empty_plan():
    with pytest.raises(LLMError, match="empty"):
        validate_scenarios([], CRITERIA)


def test_rejects_a_scenario_citing_an_unknown_criterion():
    """The whole point of the plan is traceability; a citation the CR does not
    contain is worse than no citation, because the matrix would render it."""
    scenario = scenario_from_dict(_raw(acceptance_criteria=["AC-9"]))
    with pytest.raises(LLMError, match="unknown acceptance criterion"):
        validate_scenarios([scenario], CRITERIA)


def test_rejects_a_scenario_citing_nothing():
    scenario = scenario_from_dict(_raw(acceptance_criteria=[]))
    with pytest.raises(LLMError, match="cites no acceptance criterion"):
        validate_scenarios([scenario], CRITERIA)


def test_allows_an_untraced_scenario_when_the_ticket_has_no_criteria():
    """An ad-hoc ticket has no CR to trace to; a plan is still better than none."""
    validate_scenarios([scenario_from_dict(_raw(acceptance_criteria=[]))], [])


def test_rejects_an_unknown_kind():
    with pytest.raises(LLMError, match="expected one of"):
        validate_scenarios([scenario_from_dict(_raw(kind="smoke"))], CRITERIA)


def test_rejects_duplicate_ids():
    plan = [scenario_from_dict(_raw()), scenario_from_dict(_raw(title="Other"))]
    with pytest.raises(LLMError, match="Duplicate scenario id"):
        validate_scenarios(plan, CRITERIA)


def test_rejects_a_scenario_with_no_expected_result():
    with pytest.raises(LLMError, match="no expected result"):
        validate_scenarios([scenario_from_dict(_raw(expected=" "))], CRITERIA)


def test_rejects_a_scenario_with_no_steps():
    with pytest.raises(LLMError, match="no steps"):
        validate_scenarios([scenario_from_dict(_raw(steps=[]))], CRITERIA)


def test_rejects_secret_shaped_content():
    leaked = _raw(test_data="use sk-abcdefghijklmnopqrstuvwxyz012345")
    with pytest.raises(LLMError, match="secret-shaped"):
        validate_scenarios([scenario_from_dict(leaked)], CRITERIA)


def test_rejects_more_scenarios_than_the_cap():
    plan = [
        scenario_from_dict(_raw(id=f"TS-{index:02d}")) for index in range(MAX_SCENARIOS + 1)
    ]
    with pytest.raises(LLMError, match="cap is"):
        validate_scenarios(plan, CRITERIA)


def test_scenario_from_dict_tolerates_string_shorthand():
    """The tester's edited plan comes back through this door too, so a single
    step or a single criterion arriving unwrapped must not explode."""
    scenario = scenario_from_dict(_raw(steps="only step", acceptance_criteria="AC-1"))
    assert scenario.steps == ("only step",)
    assert scenario.acceptance_criteria == ("AC-1",)


def test_uncovered_criteria_lists_the_gaps():
    plan = [scenario_from_dict(_raw())]
    assert uncovered_criteria(plan, CRITERIA) == ["AC-2"]


def test_draft_scenarios_rejects_a_non_json_response():
    with patch.object(scenarios_mod, "complete", return_value="not json at all"):
        with pytest.raises(LLMError, match="not valid JSON"):
            draft_scenarios("Acceptance criteria:\n- A thing happens.\n")


def test_draft_scenarios_strips_markdown_fences():
    payload = {"scenarios": [_raw(acceptance_criteria=["AC-1"])]}
    fenced = "```json\n" + json.dumps(payload) + "\n```"
    with patch.object(scenarios_mod, "complete", return_value=fenced):
        draft = draft_scenarios("Acceptance criteria:\n- The form has a Priority field.\n")
    assert [s.id for s in draft.scenarios] == ["TS-01"]


def test_draft_scenarios_reports_uncovered_criteria():
    payload = {"scenarios": [_raw(acceptance_criteria=["AC-1"])]}
    cr_text = (
        "Acceptance criteria:\n"
        "- The form has a Priority field.\n"
        "- Existing flows are unaffected.\n"
    )
    with patch.object(scenarios_mod, "complete", return_value=json.dumps(payload)):
        draft = draft_scenarios(cr_text)
    assert draft.uncovered_criteria == ["AC-2"]


def test_prompt_carries_the_criteria_ids_verbatim():
    from s3_enhancement.scenarios import build_prompt

    prompt = build_prompt("some cr", CRITERIA, target=MOCKAPP_AMENDMENT_FIELD_ADD)
    assert "AC-1: The form has a Priority field." in prompt
    assert "AC-2: Existing flows are unaffected." in prompt


def test_every_demo_target_has_a_distinct_scenario_cache_key():
    """Shared cache keys silently serve one target's plan for another --
    common/llm.py keys on the literal, not the prompt."""
    from s3_enhancement import targets

    keys = [
        target.cache_key("test_scenarios")
        for target in (
            targets.MOCKAPP_TIER_UPGRADE,
            targets.MOCKAPP_AMENDMENT_FIELD_ADD,
            targets.CLAIMSPORTAL_CLAIMS_DEDUCTIBLE,
        )
    ]
    assert len(set(keys)) == len(keys)
