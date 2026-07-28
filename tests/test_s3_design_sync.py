import json
from pathlib import Path
from unittest.mock import patch

import pytest

from common.llm import LLMError
from s3_enhancement import codegen, design_sync

SETTLEMENT = "mockapp/systems/legacy_java_platform/settlement"
BILLING = "mockapp/systems/legacy_java_platform/billing"


# --- stage 1: impact detection (no LLM, no file reads) ----------------------


def test_demo_crs_touch_no_documented_subsystem() -> None:
    """The load-bearing safety property: all three demo CRs change files that
    live outside every DESIGN.md-bearing directory, so the feature is a silent
    no-op on stage and never makes a provider call during a demo."""
    for applied in (
        ["mockapp/core/models.py", "mockapp/core/db.py", "mockapp/core/coverage.py"],
        ["mockapp/app.py", "mockapp/core/endorsements.py"],
        ["sandbox/spring-demo/claims-service/src/main/java/com/maplesure/claims/ClaimRules.java"],
    ):
        assert design_sync.find_affected_subsystems(applied) == ()


def test_detects_the_subsystem_owning_an_applied_file() -> None:
    impacts = design_sync.find_affected_subsystems(
        [f"{SETTLEMENT}/SettlementHandler01.java", "mockapp/core/db.py"]
    )
    assert len(impacts) == 1
    assert impacts[0].subsystem == SETTLEMENT
    assert impacts[0].design_doc == f"{SETTLEMENT}/DESIGN.md"
    assert impacts[0].applied_files == (f"{SETTLEMENT}/SettlementHandler01.java",)


def test_groups_multiple_files_and_reports_every_affected_subsystem() -> None:
    impacts = design_sync.find_affected_subsystems(
        [
            f"{SETTLEMENT}/SettlementHandler02.java",
            f"{SETTLEMENT}/SettlementHandler01.java",
            f"{BILLING}/BillingHandler01.java",
        ]
    )
    assert [impact.subsystem for impact in impacts] == [BILLING, SETTLEMENT]
    # Sorted within a subsystem, so the UI ordering is stable run to run.
    assert impacts[1].applied_files == (
        f"{SETTLEMENT}/SettlementHandler01.java",
        f"{SETTLEMENT}/SettlementHandler02.java",
    )


def test_a_file_is_attributed_to_the_most_specific_subsystem(tmp_path: Path) -> None:
    """A nested documented subsystem must claim its own file rather than the
    file matching both it and its documented parent."""
    parent = tmp_path / "platform"
    child = parent / "pricing"
    child.mkdir(parents=True)
    for directory in (parent, child):
        (directory / "DESIGN.md").write_text("## Scope keywords\n\nstuff\n", encoding="utf-8")

    impacts = design_sync.find_affected_subsystems(
        ["platform/pricing/Rate.java"], design_doc_root=tmp_path
    )
    assert [impact.subsystem for impact in impacts] == ["platform/pricing"]


def test_no_design_docs_under_the_root_means_no_impacts(tmp_path: Path) -> None:
    assert design_sync.find_affected_subsystems(["a/b.py"], design_doc_root=tmp_path) == ()


# --- stage 2: doc review ----------------------------------------------------


def _canned(still_accurate: bool, updated_doc: object = None) -> str:
    return json.dumps(
        {
            "still_accurate": still_accurate,
            "reason": "because reasons",
            "updated_doc": updated_doc,
        }
    )


def _impact() -> design_sync.SubsystemImpact:
    return design_sync.SubsystemImpact(
        subsystem=SETTLEMENT,
        design_doc=f"{SETTLEMENT}/DESIGN.md",
        applied_files=(f"{SETTLEMENT}/SettlementHandler01.java",),
    )


def test_accurate_doc_produces_no_proposal() -> None:
    with patch("s3_enhancement.design_sync.complete", return_value=_canned(True)):
        finding = design_sync.review_design_doc(_impact(), "some diff")

    assert finding.still_accurate is True
    assert finding.proposal_id == ""
    assert finding.diff_text == ""


def test_stale_doc_is_staged_as_its_own_applyable_proposal() -> None:
    updated = "# Settlement Subsystem\n\n## Scope keywords\n\nbrand new keywords\n"
    with patch("s3_enhancement.design_sync.complete", return_value=_canned(False, updated)):
        finding = design_sync.review_design_doc(_impact(), "some diff")

    assert finding.still_accurate is False
    assert finding.proposal_id
    # It rides the ordinary review path: the staged content is what apply would write.
    staged = codegen.OUT_ROOT / finding.proposal_id / "staged" / finding.design_doc
    assert staged.read_text(encoding="utf-8") == updated
    assert finding.diff_text


def test_stale_verdict_without_replacement_text_is_still_reported() -> None:
    """A "needs updating" verdict with no document is a real signal — surface it
    without a diff rather than dropping it or inventing a document."""
    with patch("s3_enhancement.design_sync.complete", return_value=_canned(False, None)):
        finding = design_sync.review_design_doc(_impact(), "some diff")

    assert finding.still_accurate is False
    assert finding.reason == "because reasons"
    assert finding.proposal_id == ""


def test_review_prompt_carries_the_doc_the_diff_and_the_scope_keywords_rationale() -> None:
    prompt = design_sync.build_review_prompt(_impact(), "DOC BODY", "DIFF BODY")
    assert "DOC BODY" in prompt
    assert "DIFF BODY" in prompt
    assert "## Scope keywords" in prompt
    assert f"{SETTLEMENT}/SettlementHandler01.java" in prompt


def test_review_omits_a_fixed_cache_key() -> None:
    """Input genuinely varies per change, so it must use the content-hash cache
    — a pinned key would serve one recorded verdict for every future change."""
    with patch("s3_enhancement.design_sync.complete", return_value=_canned(True)) as mock_complete:
        design_sync.review_design_doc(_impact(), "some diff")

    assert "cache_key" not in mock_complete.call_args.kwargs
    assert mock_complete.call_args.kwargs["json_mode"] is True


def test_malformed_model_response_raises() -> None:
    with patch("s3_enhancement.design_sync.complete", return_value="not json"):
        with pytest.raises(LLMError):
            design_sync.review_design_doc(_impact(), "some diff")


# --- review_after_apply: orchestration + fail-soft --------------------------


def test_no_affected_subsystem_short_circuits_before_any_provider_call() -> None:
    with patch("s3_enhancement.design_sync.complete") as mock_complete:
        result = design_sync.review_after_apply(["mockapp/core/db.py"])

    mock_complete.assert_not_called()
    assert result.checked is True
    assert result.impacts == ()
    assert result.stale_docs == ()


def test_provider_failure_degrades_instead_of_raising() -> None:
    """Runs immediately after Apply — an unreachable model must never turn an
    applied change into a failed one."""
    with patch(
        "s3_enhancement.design_sync.complete", side_effect=LLMError("no provider reachable")
    ):
        result = design_sync.review_after_apply([f"{SETTLEMENT}/SettlementHandler01.java"])

    assert result.checked is False
    assert "no provider reachable" in result.unavailable_reason
    assert result.impacts  # the deterministic half of the answer survives
    assert result.stale_docs == ()


def test_stale_docs_helper_filters_to_what_needs_action() -> None:
    with patch(
        "s3_enhancement.design_sync.complete",
        side_effect=[_canned(True), _canned(False, "# new doc\n")],
    ):
        result = design_sync.review_after_apply(
            [
                f"{BILLING}/BillingHandler01.java",
                f"{SETTLEMENT}/SettlementHandler01.java",
            ]
        )

    assert result.checked is True
    assert len(result.findings) == 2
    assert len(result.stale_docs) == 1
    assert result.stale_docs[0].subsystem == SETTLEMENT


def test_missing_proposal_diff_is_tolerated() -> None:
    assert design_sync.read_proposal_diff("no-such-proposal") == ""
    assert design_sync.read_proposal_diff("") == ""


# --- the shared staging seam ------------------------------------------------


def test_stage_files_as_proposal_round_trips_through_apply_change(tmp_path: Path) -> None:
    """The staged proposal must be applyable by the *existing* apply path — the
    whole reason design_sync stages instead of writing files itself."""
    target_rel = "s3_enhancement/out/.design_sync_seam_check.md"
    proposal_id, diff_text = codegen.stage_files_as_proposal({target_rel: "hello\n"})

    assert diff_text
    applied = codegen.apply_change(proposal_id)
    assert applied == [target_rel]

    written = codegen.REPO_ROOT / target_rel
    try:
        assert written.read_text(encoding="utf-8") == "hello\n"
    finally:
        written.unlink(missing_ok=True)
