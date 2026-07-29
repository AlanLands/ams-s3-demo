"""Verifies s3_enhancement/release.py -- the derived deployment plan, the
release record's evidence assembly, and the "not evidenced" honesty check."""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import patch

import pytest

from common.llm import LLMError
from s3_enhancement import docgen, targets
from s3_enhancement.acceptance import Criterion
from s3_enhancement.designdoc import render_release_record_html
from s3_enhancement.diagram import build_change_map
from s3_enhancement.docgen import ReleaseNoteSet, draft_release_note_set
from s3_enhancement.release import (
    ReleaseRecord,
    SuiteEvidence,
    build_deployment_plan,
    collect_approvals,
    unproven_claims,
)
from s3_enhancement.scenarios import Scenario
from s3_enhancement.testrun import TestCase as _TestCase
from s3_enhancement.traceability import build_matrix


def _scenario(sid: str, title: str, ref: str) -> Scenario:
    return Scenario(sid, title, "positive", (ref,), "", "", ("step",), "ok")


def _case(name: str, status: str = "passed") -> _TestCase:
    return _TestCase(name, "cls", name.replace("_", " "), status, 0.0, None)


SPRING = targets.SPRINGDEMO_CLAIMS_DEDUCTIBLE
POLICYCORE = targets.MOCKAPP_ENDORSEMENT_FIELD_ADD


# --- deployment plan --------------------------------------------------------


def test_callee_deploys_before_caller():
    """claims-service calls policy-service. Ship claims first and it spends
    the gap reading a field policy-service has not deployed yet."""
    plan = build_deployment_plan(SPRING, build_change_map(SPRING))
    assert plan.service_order == ["policy-service", "claims-service"]
    assert "policy-service first" in plan.order_reason


def test_single_service_plan_claims_no_ordering_constraint():
    plan = build_deployment_plan(POLICYCORE, build_change_map(POLICYCORE))
    assert plan.service_order == ["policycore"]
    assert plan.order_reason == ""


def test_plan_includes_the_targets_own_migration_step():
    plan = build_deployment_plan(POLICYCORE, build_change_map(POLICYCORE))
    migrate = [step for step in plan.steps if step.kind == "migrate"]
    assert len(migrate) == 1
    assert "apps.policycore.core.seed" in migrate[0].command


def test_plan_omits_migration_for_a_target_that_has_none():
    plan = build_deployment_plan(SPRING, build_change_map(SPRING))
    assert not [step for step in plan.steps if step.kind == "migrate"]


def test_plan_verifies_with_the_regression_suite():
    plan = build_deployment_plan(SPRING, build_change_map(SPRING))
    verify = [step for step in plan.steps if step.kind == "verify"]
    assert len(verify) == 1
    assert "PolicyApiRegressionTest" in verify[0].command


def test_rollback_reverses_the_deploy_order():
    plan = build_deployment_plan(SPRING, build_change_map(SPRING))
    assert plan.rollback
    restore = plan.rollback[0]
    # claims-service (the caller) comes down first.
    assert restore.detail.index("claims-service") < restore.detail.index("policy-service")


def test_rollback_is_itself_verified():
    plan = build_deployment_plan(POLICYCORE, build_change_map(POLICYCORE))
    assert any("regression" in step.title.lower() for step in plan.rollback)


def test_plan_resolves_the_python_placeholder():
    """`{python}` is a runtime placeholder; a human reading the plan needs a
    command they can paste."""
    plan = build_deployment_plan(POLICYCORE, build_change_map(POLICYCORE))
    assert not any("{python}" in step.command for step in plan.steps + plan.rollback)


# --- approvals and gaps -----------------------------------------------------


def test_collect_approvals_keeps_only_human_decisions():
    events = [
        {"actor": "ai", "action": "tests_generated", "detail": "x", "ts": "t1"},
        {"actor": "human", "action": "test_scenarios_approved", "detail": "9 by Priya", "ts": "t2"},
        {"actor": "system", "action": "regression_passed", "detail": "15/15", "ts": "t3"},
    ]
    approvals = collect_approvals(events)
    assert [item["action"] for item in approvals] == ["test scenarios approved"]


def test_unproven_lists_every_kind_of_gap():
    criteria = [
        Criterion("AC-1", "Covered and passing."),
        Criterion("AC-2", "Planned but not automated."),
        Criterion("AC-3", "Nobody planned for this."),
    ]
    scenarios = [
        _scenario("TS-01", "Persist the priority field", "AC-1"),
        _scenario("TS-02", "Something nothing tests", "AC-2"),
    ]
    matrix = build_matrix(
        criteria,
        scenarios,
        generated_cases=[_case("test_persist_the_priority_field")],
    )
    gaps = unproven_claims(matrix, [SuiteEvidence("Generated suite", True, 1, 1)])

    assert any("AC-2" in gap and "no automated test" in gap for gap in gaps)
    assert any("AC-3" in gap and "no test scenario" in gap for gap in gaps)
    # The regression suite never ran, and that is a gap in its own right.
    assert any("regression suite was not run" in gap for gap in gaps)


def test_unproven_flags_a_suite_that_failed():
    gaps = unproven_claims(None, [SuiteEvidence("Regression (pre-existing)", False, 15, 14)])
    assert any("did not pass" in gap for gap in gaps)


def test_unproven_is_empty_when_everything_is_evidenced():
    criteria = [Criterion("AC-1", "Covered.")]
    scenarios = [_scenario("TS-01", "Persist the priority field", "AC-1")]
    matrix = build_matrix(
        criteria,
        scenarios,
        generated_cases=[_case("test_persist_the_priority_field")],
    )
    evidence = [
        SuiteEvidence("Generated suite", True, 1, 1),
        SuiteEvidence("Regression (pre-existing)", True, 15, 15),
    ]
    assert unproven_claims(matrix, evidence) == []


# --- the rendered record ----------------------------------------------------


def _record(**overrides) -> ReleaseRecord:
    base = dict(
        cr_label="CR-2026-042",
        ticket_key="AMS-102",
        released_by="Priya Nair",
        generated_at=datetime(2026, 7, 29, 20, 30),
        changed_files=["apps/policycore/core/endorsements.py"],
        criteria=[],
        matrix=None,
        evidence=[SuiteEvidence("Generated suite", True, 4, 4)],
        approvals=[{"ts": "t", "action": "test scenarios approved", "detail": "by Priya"}],
        plan=build_deployment_plan(POLICYCORE, build_change_map(POLICYCORE)),
        notes=ReleaseNoteSet("Client text.", "Ops text.", "User text."),
    )
    base.update(overrides)
    return ReleaseRecord(**base)


def test_record_html_states_what_it_could_not_evidence():
    """A record that only lists successes is marketing."""
    html = render_release_record_html(_record(unproven=["AC-4 has no test scenario covering it."]))
    assert "Not evidenced by this release" in html
    assert "AC-4 has no test scenario" in html


def test_record_html_marks_the_notes_as_the_ai_authored_part():
    html = render_release_record_html(_record())
    assert "AI-drafted; the rest of this record is computed." in html


def test_record_html_carries_all_three_notes():
    html = render_release_record_html(_record())
    for text in ("Client text.", "Ops text.", "User text."):
        assert text in html


def test_record_html_survives_a_release_with_no_notes():
    """The record's value is the evidence; an unreachable model at release
    time must not stop the artifact being produced."""
    html = render_release_record_html(_record(notes=None))
    assert "Release notes" not in html
    assert "What shipped" in html


def test_record_html_escapes_model_text():
    html = render_release_record_html(
        _record(notes=ReleaseNoteSet("<script>alert(1)</script>", "ops", "new"))
    )
    assert "<script>alert(1)</script>" not in html


# --- the note set ------------------------------------------------------------


def test_note_set_rejects_a_response_missing_an_audience():
    payload = json.dumps({"changelog": "x", "whats_new": "y"})
    with patch.object(docgen, "complete", return_value=payload):
        with pytest.raises(LLMError, match="missing 'ops_note'"):
            draft_release_note_set("cr")


def test_note_set_rejects_secret_shaped_content():
    payload = json.dumps(
        {
            "changelog": "use sk-abcdefghijklmnopqrstuvwxyz012345",
            "ops_note": "o",
            "whats_new": "w",
        }
    )
    with patch.object(docgen, "complete", return_value=payload):
        with pytest.raises(LLMError, match="secret-shaped"):
            draft_release_note_set("cr")


def test_note_set_strips_markdown_fences():
    body = json.dumps({"changelog": "c", "ops_note": "o", "whats_new": "w"})
    payload = "```json\n" + body + "\n```"
    with patch.object(docgen, "complete", return_value=payload):
        notes = draft_release_note_set("cr")
    assert notes.changelog == "c"


def test_note_set_uses_a_distinct_cache_beat_per_target():
    """Sharing the old release_notes key would replay prose into a caller
    expecting JSON -- common/llm.py keys on the literal, not the shape."""
    keys = {
        target.cache_key("release_note_set")
        for target in (
            targets.MOCKAPP_COVERAGE_UPGRADE,
            targets.MOCKAPP_ENDORSEMENT_FIELD_ADD,
            targets.SPRINGDEMO_CLAIMS_DEDUCTIBLE,
        )
    }
    assert len(keys) == 3
    assert targets.MOCKAPP_COVERAGE_UPGRADE.cache_key(
        "release_note_set"
    ) != targets.MOCKAPP_COVERAGE_UPGRADE.cache_key("release_notes")
