"""Verifies s3_enhancement/acceptance.py -- deterministic extraction of a CR's
acceptance criteria, and s3_enhancement/traceability.py's matrix assembly."""

from __future__ import annotations

from s3_enhancement import cr, targets
from s3_enhancement.acceptance import Criterion, parse_acceptance_criteria
from s3_enhancement.scenarios import Scenario

# Aliased: pytest tries to collect any imported class named Test*, and
# warns because this one is a dataclass with a constructor.
from s3_enhancement.testrun import TestCase as _TestCase
from s3_enhancement.traceability import build_matrix, match_scenario

SIMPLE_CR = """CR-2026-999: Something

Requested by: Someone

Acceptance criteria:
- The first thing happens.
- The second thing spans
  two source lines.
- Existing flows are unaffected.

Notes:
- This bullet is in a different section and is not a criterion.
"""


def _case(name: str, status: str = "passed") -> _TestCase:
    return _TestCase(name, "cls", name.replace("_", " "), status, 0.01, None)


def _scenario(sid: str, title: str, refs: list[str], kind: str = "positive") -> Scenario:
    return Scenario(
        id=sid,
        title=title,
        kind=kind,
        acceptance_criteria=tuple(refs),
        preconditions="",
        test_data="",
        steps=("do it",),
        expected=title,
    )


def test_parses_numbered_criteria_in_order():
    criteria = parse_acceptance_criteria(SIMPLE_CR)
    assert [c.id for c in criteria] == ["AC-1", "AC-2", "AC-3"]
    assert criteria[0].text == "The first thing happens."


def test_unwraps_hard_wrapped_criterion():
    criteria = parse_acceptance_criteria(SIMPLE_CR)
    assert criteria[1].text == "The second thing spans two source lines."


def test_stops_at_the_end_of_the_criteria_section():
    """CR-2026-041 follows its criteria with an explicitly out-of-scope list;
    pulling those in would invent requirements the CR disclaims."""
    criteria = parse_acceptance_criteria(SIMPLE_CR)
    assert all("different section" not in c.text for c in criteria)


def test_flags_the_regression_criterion():
    criteria = parse_acceptance_criteria(SIMPLE_CR)
    assert [c.is_regression for c in criteria] == [False, False, True]


def test_returns_empty_for_a_ticket_with_no_criteria():
    assert parse_acceptance_criteria("Just some free text about a problem.") == []


def test_every_demo_cr_states_criteria_including_a_regression_one():
    for target in (
        targets.MOCKAPP_COVERAGE_UPGRADE,
        targets.MOCKAPP_ENDORSEMENT_FIELD_ADD,
        targets.CLAIMSPORTAL_CLAIMS_DEDUCTIBLE,
    ):
        criteria = parse_acceptance_criteria(cr.render_cr("Elite", target=target))
        assert criteria, f"{target.target_id} CR has no acceptance criteria"
        assert any(c.is_regression for c in criteria), (
            f"{target.target_id} CR states no regression criterion"
        )


def test_match_picks_the_clear_winner():
    scenario = _scenario("TS-01", "Reject claim below deductible", ["AC-1"])
    cases = [_case("testDecideRejectedBelowDeductible"), _case("testPayableCalculation")]
    match = match_scenario(scenario, cases)
    assert match is not None and match.name == "testDecideRejectedBelowDeductible"


def test_match_declines_an_ambiguous_pairing():
    """Two equally plausible tests must resolve to no match, never a guess --
    a wrongly matched row claims coverage that does not exist."""
    scenario = _scenario("TS-01", "Reject claim over limit", ["AC-1"])
    cases = [_case("test_reject_claim_over_limit"), _case("test_reject_claim_over_limit_two")]
    assert match_scenario(scenario, cases) is None


def test_match_declines_on_a_single_shared_token():
    scenario = _scenario("TS-01", "Verify existing coverage tiers are displayed", ["AC-1"])
    assert match_scenario(scenario, [_case("test_default_tier_is_standard")]) is None


def test_matrix_routes_regression_criteria_to_the_pre_existing_suite():
    criteria = [
        Criterion("AC-1", "The new field is persisted."),
        Criterion("AC-2", "Existing flows are unaffected."),
    ]
    scenarios = [
        _scenario("TS-01", "Persist the new priority field", ["AC-1"]),
        _scenario("TS-02", "Existing flows still work", ["AC-2"], kind="regression"),
    ]
    matrix = build_matrix(
        criteria,
        scenarios,
        generated_cases=[_case("test_persist_the_new_priority_field")],
        regression_cases=[_case("test_policy_list"), _case("test_claim_list")],
    )

    assert matrix.rows[0].covered_by == "generated"
    assert matrix.rows[1].covered_by == "regression"
    assert matrix.rows[1].test_names == ["2 pre-existing tests"]
    assert matrix.fully_covered


def test_matrix_reports_a_criterion_no_scenario_covers():
    criteria = [Criterion("AC-1", "Covered."), Criterion("AC-2", "Forgotten.")]
    scenarios = [_scenario("TS-01", "Covered thing happens", ["AC-1"])]
    matrix = build_matrix(
        criteria, scenarios, generated_cases=[_case("test_covered_thing_happens")]
    )

    assert matrix.rows[1].status == "no_scenario"
    assert matrix.summary()["no_scenario"] == 1
    assert not matrix.fully_covered


def test_matrix_reports_a_planned_but_unautomated_criterion():
    criteria = [Criterion("AC-1", "Something specific.")]
    scenarios = [_scenario("TS-01", "Check the specific something", ["AC-1"])]
    matrix = build_matrix(
        criteria, scenarios, generated_cases=[_case("test_entirely_unrelated_behaviour")]
    )

    assert matrix.rows[0].status == "not_automated"
    assert matrix.rows[0].scenario_ids == ["TS-01"]


def test_matrix_marks_a_criterion_failed_when_its_test_failed():
    criteria = [Criterion("AC-1", "Something specific.")]
    scenarios = [_scenario("TS-01", "Persist the priority field", ["AC-1"])]
    matrix = build_matrix(
        criteria,
        scenarios,
        generated_cases=[_case("test_persist_the_priority_field", status="failed")],
    )

    assert matrix.rows[0].status == "failed"


def test_matrix_before_any_run_reports_not_run():
    criteria = [Criterion("AC-1", "Something.")]
    scenarios = [_scenario("TS-01", "Do something", ["AC-1"])]
    matrix = build_matrix(criteria, scenarios)
    assert matrix.rows[0].status == "not_run"
