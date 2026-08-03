import json
from unittest.mock import patch

import pytest

from common.llm import LLMError
from s3_enhancement.repo_match import suggest_target_repo

PROJECTS = [
    {"id": 1, "name": "policy-service", "description": "MapleSure policy and coverage APIs"},
    {"id": 2, "name": "claims-portal", "description": "Customer-facing claims submission UI"},
    {"id": 3, "name": "billing-batch", "description": "Nightly contribution billing jobs"},
]


def test_suggest_target_repo_parses_best_match_and_alternates():
    canned = json.dumps(
        {
            "best_match_id": "1",
            "confidence": "high",
            "reasoning": "The user story is about plan tiers, which lives in policy-service.",
            "alternates": [{"id": "2", "reasoning": "Claims portal also shows coverage info."}],
        }
    )
    with patch("s3_enhancement.repo_match.complete", return_value=canned) as mock_complete:
        suggestion = suggest_target_repo("add a tier-upgrade option", PROJECTS)

    assert mock_complete.call_args.kwargs["json_mode"] is True
    assert "cache_key" not in mock_complete.call_args.kwargs
    assert suggestion.best_match.project_id == "1"
    assert suggestion.best_match.confidence == "high"
    assert len(suggestion.alternates) == 1
    assert suggestion.alternates[0].project_id == "2"


def test_suggest_target_repo_raises_when_model_picks_unknown_id():
    canned = json.dumps({"best_match_id": "999", "confidence": "high", "reasoning": "..."})
    with patch("s3_enhancement.repo_match.complete", return_value=canned):
        with pytest.raises(LLMError, match="not in the candidate list"):
            suggest_target_repo("add a tier-upgrade option", PROJECTS)


def test_suggest_target_repo_drops_alternates_with_unknown_ids():
    canned = json.dumps(
        {
            "best_match_id": "1",
            "reasoning": "match",
            "alternates": [{"id": "999", "reasoning": "not real"}],
        }
    )
    with patch("s3_enhancement.repo_match.complete", return_value=canned):
        suggestion = suggest_target_repo("add a tier-upgrade option", PROJECTS)
    assert suggestion.alternates == ()


def test_suggest_target_repo_raises_with_no_candidates():
    with pytest.raises(LLMError, match="no candidate repositories"):
        suggest_target_repo("add a tier-upgrade option", [])


def test_suggest_target_repo_raises_on_malformed_json():
    with patch("s3_enhancement.repo_match.complete", return_value="not json"):
        with pytest.raises(LLMError):
            suggest_target_repo("add a tier-upgrade option", PROJECTS)
