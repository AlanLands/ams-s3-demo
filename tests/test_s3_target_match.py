"""Tests for s3_enhancement/target_match.py — resolving a user story's owning Target
from its text alone, the piece that lets a new repo/target be picked up by
user story content rather than a hardcoded ticket-key table."""

from __future__ import annotations

import json
from unittest.mock import patch

from s3_enhancement import targets
from s3_enhancement.target_match import resolve_target_for_story


def test_all_three_pinned_crs_resolve_by_story_id_alone():
    """Every user story committed under stories/ today must resolve via tier 1 (exact user story
    identifier match) with no LLM call at all — this is the byte-identical
    identity every existing target already declares via story_template_path."""
    for target in targets.all_targets():
        if target.story_template_path is None:
            continue
        story_text = target.story_template_path.read_text(encoding="utf-8")
        with patch("s3_enhancement.target_match.complete") as mock_complete:
            match = resolve_target_for_story(story_text)
        mock_complete.assert_not_called()
        assert match.method == "story_id"
        assert match.target is target
        assert match.resolved
        assert not match.needs_confirmation


def test_new_story_with_no_pinned_title_resolves_by_application_header():
    """A brand-new user story for an already-registered application, whose title
    doesn't match any registered target's story_template_path yet, still
    resolves deterministically off its Application: header -- exactly the
    "just add another repo" case, so long as that application has exactly
    one registered target."""
    story_text = (
        "US-2026-999: Some Future Enrolment Change\n\n"
        "Requested by: MapleSure Group Retirement Product\n"
        "Application: EnrolDirect (online enrolment channel)\n"
        "Priority: P4 - small enhancement\n\n"
        "Description:\nSomething not yet built.\n"
    )
    with patch("s3_enhancement.target_match.complete") as mock_complete:
        match = resolve_target_for_story(story_text)
    mock_complete.assert_not_called()
    assert match.method == "application_header"
    assert match.target is targets.ENROLDIRECT_PROSPECT_ACCESS
    assert match.resolved


def test_application_header_is_ambiguous_when_app_has_multiple_targets():
    """PolicyCore hosts two registered targets (US-2026-041, US-2026-042) --
    a user story whose title matches neither of them can't be resolved by the
    Application: header alone, and must fall through to the AI tier rather
    than silently guessing one of the two."""
    story_text = (
        "US-2026-998: Some Future PolicyCore Change\n\n"
        "Application: PolicyCore (policy/claims portal)\n\n"
        "Description:\nSomething not yet built.\n"
    )
    canned = json.dumps(
        {
            "target_id": targets.MOCKAPP_AMENDMENT_FIELD_ADD.target_id,
            "confidence": "medium",
            "reasoning": "Closest existing PolicyCore change in shape.",
        }
    )
    with patch("s3_enhancement.target_match.complete", return_value=canned) as mock_complete:
        match = resolve_target_for_story(story_text)
    mock_complete.assert_called_once()
    assert mock_complete.call_args.kwargs["json_mode"] is True
    assert "cache_key" not in mock_complete.call_args.kwargs
    assert match.method == "ai"
    assert match.target is targets.MOCKAPP_AMENDMENT_FIELD_ADD
    assert match.confidence == "medium"
    assert match.needs_confirmation


def test_ai_tier_high_confidence_needs_no_confirmation():
    story_text = "US-2026-997: Unlabeled change with no Application header.\n"
    canned = json.dumps(
        {
            "target_id": targets.MOCKAPP_TIER_UPGRADE.target_id,
            "confidence": "high",
            "reasoning": "Matches coverage-tier language closely.",
        }
    )
    with patch("s3_enhancement.target_match.complete", return_value=canned):
        match = resolve_target_for_story(story_text)
    assert match.method == "ai"
    assert not match.needs_confirmation


def test_ai_tier_returns_unresolved_when_model_picks_unknown_target_id():
    story_text = "US-2026-996: Unlabeled change.\n"
    canned = json.dumps({"target_id": "not-a-real-target", "confidence": "high", "reasoning": "x"})
    with patch("s3_enhancement.target_match.complete", return_value=canned):
        match = resolve_target_for_story(story_text)
    assert match.method == "unresolved"
    assert not match.resolved


def test_ai_tier_degrades_to_unresolved_on_llm_error():
    from common.llm import LLMError

    story_text = "US-2026-995: Unlabeled change.\n"
    with patch("s3_enhancement.target_match.complete", side_effect=LLMError("boom")):
        match = resolve_target_for_story(story_text)
    assert match.method == "unresolved"
    assert not match.resolved


def test_story_id_tier_takes_priority_over_application_header():
    """A user story whose title exactly matches a registered target wins on tier 1
    even if its Application: header could also resolve via tier 2 -- the
    exact identifier is the stronger signal, and checking it first also
    means the common case never needs the header parse at all."""
    real = targets.MOCKAPP_AMENDMENT_FIELD_ADD
    story_text = real.story_template_path.read_text(encoding="utf-8")
    with patch("s3_enhancement.target_match.complete") as mock_complete:
        match = resolve_target_for_story(story_text)
    mock_complete.assert_not_called()
    assert match.method == "story_id"
    assert match.target is real


def _ai_response(**extra) -> str:
    return json.dumps(
        {
            "target_id": targets.MOCKAPP_AMENDMENT_FIELD_ADD.target_id,
            "confidence": "high",
            "reasoning": "Closest match.",
            **extra,
        }
    )


def test_ai_tier_ranks_every_candidate_best_first():
    """The ranking is what makes an AI pick reviewable — a reviewer needs to
    see the runner-up's score, not just the winner's name."""
    canned = _ai_response(
        ranking=[
            {"target_id": targets.ENROLDIRECT_PROSPECT_ACCESS.target_id, "score": 5, "reasoning": "c"},
            {"target_id": targets.MOCKAPP_AMENDMENT_FIELD_ADD.target_id, "score": 95, "reasoning": "a"},
            {"target_id": targets.MOCKAPP_TIER_UPGRADE.target_id, "score": 20, "reasoning": "b"},
        ]
    )
    with patch("s3_enhancement.target_match.complete", return_value=canned):
        match = resolve_target_for_story("US-2026-995: Unlabeled.\n")
    assert [c.score for c in match.ranking] == [95, 20, 5]
    assert match.ranking[0].target_id == match.target.target_id
    # Display names come from the registry, never from the model's echo.
    assert match.ranking[0].display_name == targets.MOCKAPP_AMENDMENT_FIELD_ADD.display_name


def test_ranking_drops_candidates_that_are_not_registered_targets():
    """A ranking row for a repo this console doesn't have would be a
    confident-looking fabrication, so it is dropped rather than rendered."""
    canned = _ai_response(
        ranking=[
            {"target_id": targets.MOCKAPP_AMENDMENT_FIELD_ADD.target_id, "score": 90},
            {"target_id": "some-repo-that-does-not-exist", "score": 80},
        ]
    )
    with patch("s3_enhancement.target_match.complete", return_value=canned):
        match = resolve_target_for_story("US-2026-994: Unlabeled.\n")
    assert [c.target_id for c in match.ranking] == [
        targets.MOCKAPP_AMENDMENT_FIELD_ADD.target_id
    ]


def test_malformed_ranking_costs_the_explanation_not_the_match():
    """A missing or junk ranking must degrade the card, never the result."""
    for bad in ("not-a-list", [], [{"score": 10}], [["wrong", "shape"]], None):
        with patch("s3_enhancement.target_match.complete", return_value=_ai_response(ranking=bad)):
            match = resolve_target_for_story("US-2026-993: Unlabeled.\n")
        assert match.target is targets.MOCKAPP_AMENDMENT_FIELD_ADD, bad
        assert match.ranking == (), bad


def test_deterministic_tiers_rank_nothing():
    """Tiers 1 and 2 never compared candidates, so they must not imply they
    did by reporting a ranking."""
    story_text = "US-2026-042: Amendment Priority Field\n"
    with patch("s3_enhancement.target_match.complete") as mock_complete:
        match = resolve_target_for_story(story_text)
    mock_complete.assert_not_called()
    assert match.method == "story_id"
    assert match.ranking == ()


def test_ranking_scores_are_clamped_to_0_100():
    canned = _ai_response(
        ranking=[
            {"target_id": targets.MOCKAPP_AMENDMENT_FIELD_ADD.target_id, "score": 900},
            {"target_id": targets.MOCKAPP_TIER_UPGRADE.target_id, "score": -50},
        ]
    )
    with patch("s3_enhancement.target_match.complete", return_value=canned):
        match = resolve_target_for_story("US-2026-992: Unlabeled.\n")
    assert [c.score for c in match.ranking] == [100, 0]
