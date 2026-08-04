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
from s3_enhancement.scm import BranchState, Commit
from s3_enhancement.testrun import TestCase as _TestCase
from s3_enhancement.traceability import build_matrix


def _scenario(sid: str, title: str, ref: str) -> Scenario:
    return Scenario(sid, title, "positive", (ref,), "", "", ("step",), "ok")


def _branch(**overrides) -> BranchState:
    base = dict(
        proposal_id="p1",
        branch="feature/AMS-103-claimsportal-claims-deductible",
        base="main",
        ticket="AMS-103",
        created_at="2026-07-30 09:00:00",
        staged_files=["repos/claimsportal/policy_service/policy.py"],
    )
    base.update(overrides)
    return BranchState(**base)


def _commit() -> Commit:
    return Commit(
        sha="abc1234",
        message="AMS-103: add claims deductible",
        files=("repos/claimsportal/policy_service/policy.py",),
        committed_at="2026-07-30 09:30:00",
    )


def _pushed_branch() -> BranchState:
    return _branch(
        commit=_commit(),
        pushed_at="2026-07-30 09:35:00",
        pipeline_id="pipeline-abc1234",
    )


def _case(name: str, status: str = "passed") -> _TestCase:
    return _TestCase(name, "cls", name.replace("_", " "), status, 0.0, None)

from tests.multiservice_fixture import TWO_SERVICE


# Was the ClaimsPortal target until it was removed on 2026-08-04; now a
# synthetic stand-in so the multi-service behaviour stays covered.
# See tests/multiservice_fixture.py.
SPRING = TWO_SERVICE
POLICYCORE = targets.MOCKAPP_AMENDMENT_FIELD_ADD


# --- deployment plan --------------------------------------------------------


def test_callee_deploys_before_caller():
    """orders_service calls ledger_service. Ship orders first and it spends
    the gap reading a field ledger_service has not deployed yet."""
    plan = build_deployment_plan(SPRING, build_change_map(SPRING))
    assert plan.service_order == ["ledger_service", "orders_service"]
    assert "ledger_service first" in plan.order_reason


def test_single_service_plan_claims_no_ordering_constraint():
    plan = build_deployment_plan(POLICYCORE, build_change_map(POLICYCORE))
    assert plan.service_order == ["policycore"]
    assert plan.order_reason == ""


def test_plan_includes_the_targets_own_migration_step():
    plan = build_deployment_plan(POLICYCORE, build_change_map(POLICYCORE))
    migrate = [step for step in plan.steps if step.kind == "migrate"]
    assert len(migrate) == 1
    assert "repos.policycore.core.seed" in migrate[0].command


def test_plan_omits_migration_for_a_target_that_has_none():
    plan = build_deployment_plan(SPRING, build_change_map(SPRING))
    assert not [step for step in plan.steps if step.kind == "migrate"]


def test_plan_verifies_with_the_regression_suite():
    plan = build_deployment_plan(SPRING, build_change_map(SPRING))
    verify = [step for step in plan.steps if step.kind == "verify"]
    assert len(verify) == 1
    assert "test_regression_twoservice.py" in verify[0].command


def test_rollback_reverses_the_deploy_order():
    plan = build_deployment_plan(SPRING, build_change_map(SPRING))
    assert plan.rollback
    restore = plan.rollback[0]
    # orders_service (the caller) comes down first.
    assert restore.detail.index("orders_service") < restore.detail.index("ledger_service")


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


def _fully_evidenced() -> tuple:
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
    return matrix, evidence


def test_no_test_evidence_gaps_when_everything_is_evidenced():
    """Every criterion covered and both suites green leaves no *test* gap.

    The source-control gap is asserted separately below — it is a claim about
    shipping, not about testing, and conflating the two is what let the old
    single assertion here pass while the record said nothing about deployment.
    """
    matrix, evidence = _fully_evidenced()
    gaps = unproven_claims(matrix, evidence, _pushed_branch())
    assert not [gap for gap in gaps if "simulated" not in gap]


# --- the source-control half of the honesty check ---------------------------
#
# S3 models branch -> commit -> push without running git (s3_enhancement/scm.py).
# These assert the record says so, in every branch state, because a modelled
# push that reads as a deployment is the one way this document could mislead the
# person signing it.


def test_a_pushed_branch_is_still_reported_as_simulated():
    matrix, evidence = _fully_evidenced()
    gaps = unproven_claims(matrix, evidence, _pushed_branch())
    assert any("simulated" in gap and "pipeline-abc1234" in gap for gap in gaps)


def test_no_branch_at_all_is_a_gap():
    """Applying straight to the working tree leaves no source-control history,
    and the record has to say that rather than stay silent about it."""
    matrix, evidence = _fully_evidenced()
    gaps = unproven_claims(matrix, evidence, None)
    assert any("No branch or commit was recorded" in gap for gap in gaps)


def test_applied_but_uncommitted_is_a_gap():
    matrix, evidence = _fully_evidenced()
    gaps = unproven_claims(matrix, evidence, _branch())
    assert any("never committed" in gap for gap in gaps)


def test_committed_but_unpushed_is_a_gap():
    matrix, evidence = _fully_evidenced()
    gaps = unproven_claims(matrix, evidence, _branch(commit=_commit()))
    assert any("not pushed" in gap and "abc1234" in gap for gap in gaps)


def test_abandoned_branch_is_a_gap():
    matrix, evidence = _fully_evidenced()
    branch = _branch(staged_files=[], abandoned_at="2026-07-30 10:00:00")
    gaps = unproven_claims(matrix, evidence, branch)
    assert any("abandoned" in gap for gap in gaps)


def test_plan_pins_the_merge_step_to_the_commit():
    """With a branch, the plan names the commit being deployed instead of
    leaving "deploy the change" to the reader."""
    plan = build_deployment_plan(
        POLICYCORE, build_change_map(POLICYCORE), branch=_pushed_branch()
    )
    merge = [step for step in plan.steps if step.kind == "merge"]
    assert len(merge) == 1
    assert merge[0].order == 1, "the merge has to come before the deploys"
    assert "abc1234" in merge[0].detail
    reverts = [step for step in plan.rollback if "revert" in step.command]
    assert reverts and "abc1234" in reverts[0].command


def test_plan_step_order_is_contiguous_with_and_without_a_branch():
    """The branch step is inserted, not appended, so every later step's order
    shifts — a duplicated or skipped number here would show up as a misnumbered
    plan in the released document."""
    change_map = build_change_map(POLICYCORE)
    for branch in (None, _pushed_branch()):
        plan = build_deployment_plan(POLICYCORE, change_map, branch=branch)
        for steps in (plan.steps, plan.rollback):
            assert [step.order for step in steps] == list(range(1, len(steps) + 1))


def test_rollback_reverts_rather_than_rewriting_history():
    plan = build_deployment_plan(
        POLICYCORE, build_change_map(POLICYCORE), branch=_pushed_branch()
    )
    commands = " ".join(step.command for step in plan.rollback)
    assert "git revert" in commands
    assert "reset --hard" not in commands and "push --force" not in commands


# --- the rendered record ----------------------------------------------------


def _record(**overrides) -> ReleaseRecord:
    base = dict(
        story_label="US-2026-042",
        ticket_key="AMS-102",
        released_by="Priya Nair",
        generated_at=datetime(2026, 7, 29, 20, 30),
        changed_files=["repos/policycore/core/amendments.py"],
        criteria=[],
        matrix=None,
        evidence=[SuiteEvidence("Generated suite", True, 4, 4)],
        approvals=[{"ts": "t", "action": "test scenarios approved", "detail": "by Priya"}],
        plan=build_deployment_plan(POLICYCORE, build_change_map(POLICYCORE)),
        notes=ReleaseNoteSet("Client text.", "Ops text.", "User text."),
    )
    base.update(overrides)
    return ReleaseRecord(**base)


def test_record_html_shows_the_branch_and_says_it_was_not_executed():
    """A reader who skims to the branch name and stops must not walk away
    thinking git ran — so the caveat sits next to the branch, not only in the
    gaps block further up."""
    html = render_release_record_html(_record(branch=_pushed_branch()))
    assert "Source control" in html
    assert "feature/AMS-103-claimsportal-claims-deductible" in html
    assert "abc1234" in html
    assert "does not run git" in html


def test_record_html_omits_source_control_when_there_was_none():
    html = render_release_record_html(_record())
    assert "Source control" not in html


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
            draft_release_note_set("story")


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
            draft_release_note_set("story")


def test_note_set_strips_markdown_fences():
    body = json.dumps({"changelog": "c", "ops_note": "o", "whats_new": "w"})
    payload = "```json\n" + body + "\n```"
    with patch.object(docgen, "complete", return_value=payload):
        notes = draft_release_note_set("story")
    assert notes.changelog == "c"


def test_note_set_uses_a_distinct_cache_beat_per_target():
    """Sharing the old release_notes key would replay prose into a caller
    expecting JSON -- common/llm.py keys on the literal, not the shape.

    Ranges over every registered target rather than a hand-listed few, so a
    target added later (or discovered from a `.s3targets.json` manifest, which
    no list here would know about) is covered without anyone remembering to
    add it.
    """
    all_targets = targets.all_targets()
    keys = {target.cache_key("release_note_set") for target in all_targets}

    assert len(keys) == len(all_targets), "two targets share a release_note_set cache key"
    for target in all_targets:
        assert target.cache_key("release_note_set") != target.cache_key("release_notes")
