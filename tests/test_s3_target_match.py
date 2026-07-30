"""Tests for s3_enhancement/target_match.py — resolving a CR's owning Target
from its text alone, the piece that lets a new repo/target be picked up by
CR content rather than a hardcoded ticket-key table."""

from __future__ import annotations

import json
from unittest.mock import patch

from s3_enhancement import targets
from s3_enhancement.target_match import resolve_target_for_cr


def test_all_three_pinned_crs_resolve_by_cr_id_alone():
    """Every CR committed under crs/ today must resolve via tier 1 (exact CR
    identifier match) with no LLM call at all — this is the byte-identical
    identity every existing target already declares via cr_template_path."""
    for target in targets.all_targets():
        if target.cr_template_path is None:
            continue
        cr_text = target.cr_template_path.read_text(encoding="utf-8")
        with patch("s3_enhancement.target_match.complete") as mock_complete:
            match = resolve_target_for_cr(cr_text)
        mock_complete.assert_not_called()
        assert match.method == "cr_id"
        assert match.target is target
        assert match.resolved
        assert not match.needs_confirmation


def test_new_cr_with_no_pinned_title_resolves_by_application_header():
    """A brand-new CR for an already-registered application, whose title
    doesn't match any registered target's cr_template_path yet, still
    resolves deterministically off its Application: header -- exactly the
    "just add another repo" case, so long as that application has exactly
    one registered target."""
    cr_text = (
        "CR-2026-999: Some Future Claims Change\n\n"
        "Requested by: MapleSure Claims Operations\n"
        "Application: ClaimsPortal (FastAPI claims intake + policy lookup services)\n"
        "Priority: P4 - small enhancement\n\n"
        "Description:\nSomething not yet built.\n"
    )
    with patch("s3_enhancement.target_match.complete") as mock_complete:
        match = resolve_target_for_cr(cr_text)
    mock_complete.assert_not_called()
    assert match.method == "application_header"
    assert match.target is targets.SPRINGDEMO_CLAIMS_DEDUCTIBLE
    assert match.resolved


def test_application_header_is_ambiguous_when_app_has_multiple_targets():
    """PolicyCore hosts two registered targets (CR-2026-041, CR-2026-042) --
    a CR whose title matches neither of them can't be resolved by the
    Application: header alone, and must fall through to the AI tier rather
    than silently guessing one of the two."""
    cr_text = (
        "CR-2026-998: Some Future PolicyCore Change\n\n"
        "Application: PolicyCore (policy/claims portal)\n\n"
        "Description:\nSomething not yet built.\n"
    )
    canned = json.dumps(
        {
            "target_id": targets.MOCKAPP_ENDORSEMENT_FIELD_ADD.target_id,
            "confidence": "medium",
            "reasoning": "Closest existing PolicyCore change in shape.",
        }
    )
    with patch("s3_enhancement.target_match.complete", return_value=canned) as mock_complete:
        match = resolve_target_for_cr(cr_text)
    mock_complete.assert_called_once()
    assert mock_complete.call_args.kwargs["json_mode"] is True
    assert "cache_key" not in mock_complete.call_args.kwargs
    assert match.method == "ai"
    assert match.target is targets.MOCKAPP_ENDORSEMENT_FIELD_ADD
    assert match.confidence == "medium"
    assert match.needs_confirmation


def test_ai_tier_high_confidence_needs_no_confirmation():
    cr_text = "CR-2026-997: Unlabeled change with no Application header.\n"
    canned = json.dumps(
        {
            "target_id": targets.MOCKAPP_COVERAGE_UPGRADE.target_id,
            "confidence": "high",
            "reasoning": "Matches coverage-tier language closely.",
        }
    )
    with patch("s3_enhancement.target_match.complete", return_value=canned):
        match = resolve_target_for_cr(cr_text)
    assert match.method == "ai"
    assert not match.needs_confirmation


def test_ai_tier_returns_unresolved_when_model_picks_unknown_target_id():
    cr_text = "CR-2026-996: Unlabeled change.\n"
    canned = json.dumps({"target_id": "not-a-real-target", "confidence": "high", "reasoning": "x"})
    with patch("s3_enhancement.target_match.complete", return_value=canned):
        match = resolve_target_for_cr(cr_text)
    assert match.method == "unresolved"
    assert not match.resolved


def test_ai_tier_degrades_to_unresolved_on_llm_error():
    from common.llm import LLMError

    cr_text = "CR-2026-995: Unlabeled change.\n"
    with patch("s3_enhancement.target_match.complete", side_effect=LLMError("boom")):
        match = resolve_target_for_cr(cr_text)
    assert match.method == "unresolved"
    assert not match.resolved


def test_cr_id_tier_takes_priority_over_application_header():
    """A CR whose title exactly matches a registered target wins on tier 1
    even if its Application: header could also resolve via tier 2 -- the
    exact identifier is the stronger signal, and checking it first also
    means the common case never needs the header parse at all."""
    real = targets.MOCKAPP_ENDORSEMENT_FIELD_ADD
    cr_text = real.cr_template_path.read_text(encoding="utf-8")
    with patch("s3_enhancement.target_match.complete") as mock_complete:
        match = resolve_target_for_cr(cr_text)
    mock_complete.assert_not_called()
    assert match.method == "cr_id"
    assert match.target is real
