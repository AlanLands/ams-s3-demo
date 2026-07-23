import json
from unittest.mock import patch

import pytest

from common.llm import LLMError
from s3_enhancement.analyze import draft_effort_estimate
from s3_enhancement.cr import render_cr


def test_draft_effort_estimate_parses_hours_and_priority():
    canned = json.dumps(
        {
            "hours_class": "~40h",
            "priority_equivalent": "p4",
            "reasoning": "Small, well-scoped UI + calculation change on an existing model.",
        }
    )

    with patch("s3_enhancement.analyze.complete", return_value=canned) as mock_complete:
        estimate = draft_effort_estimate(render_cr("Elite"))

    assert mock_complete.call_args.kwargs["cache_key"] == "s3_effort_estimate:coverage_upgrade:v2"
    assert mock_complete.call_args.kwargs["json_mode"] is True
    prompt = mock_complete.call_args.args[0]
    assert "CR-2026-041" in prompt
    assert estimate.hours_class == "~40h"
    assert estimate.priority_equivalent == "P4"
    assert "UI" in estimate.reasoning


def test_draft_effort_estimate_raises_llm_error_on_malformed_model_output():
    payload = {"hours_class": "~40h", "priority_equivalent": "P4"}
    fenced = "```json\n" + json.dumps(payload) + "\n```"
    with patch("s3_enhancement.analyze.complete", return_value=fenced):
        draft_effort_estimate(render_cr("Elite"))  # fenced JSON is still parseable

    malformed = "Sure, this looks like about 40 hours of work."
    with patch("s3_enhancement.analyze.complete", return_value=malformed):
        with pytest.raises(LLMError):
            draft_effort_estimate(render_cr("Elite"))
