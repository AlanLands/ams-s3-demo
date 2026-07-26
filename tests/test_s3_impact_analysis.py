import json
from unittest.mock import patch

import pytest

from common.llm import LLMError
from s3_enhancement.analyze import draft_adhoc_impact_analysis, draft_impact_analysis
from s3_enhancement.cr import render_cr


def test_draft_impact_analysis_surfaces_assumptions_separately_from_the_text():
    canned = json.dumps(
        {
            "impact_analysis": "Update coverage.py and app.py to add the new tier.",
            "assumptions": ["Assumed premium recalculation stays a simple ratio, not tiered."],
        }
    )

    with patch("s3_enhancement.analyze.complete", return_value=canned) as mock_complete:
        impact = draft_impact_analysis(render_cr("Elite"))

    assert mock_complete.call_args.kwargs["json_mode"] is True
    assert impact.text == "Update coverage.py and app.py to add the new tier."
    assert impact.assumptions == [
        "Assumed premium recalculation stays a simple ratio, not tiered."
    ]


def test_draft_impact_analysis_defaults_to_no_assumptions():
    """A fully-specified CR is expected to come back with an empty
    assumptions list, not an omitted/null field."""
    canned = json.dumps({"impact_analysis": "Straightforward field addition.", "assumptions": []})

    with patch("s3_enhancement.analyze.complete", return_value=canned):
        impact = draft_impact_analysis(render_cr("Elite"))

    assert impact.assumptions == []


def test_draft_impact_analysis_raises_llm_error_on_non_list_assumptions():
    malformed = json.dumps({"impact_analysis": "text", "assumptions": "not a list"})

    with patch("s3_enhancement.analyze.complete", return_value=malformed):
        with pytest.raises(LLMError):
            draft_impact_analysis(render_cr("Elite"))


def test_draft_adhoc_impact_analysis_surfaces_assumptions():
    canned = json.dumps(
        {
            "impact_analysis": "Likely touches BillingGateway's recalculation job.",
            "assumptions": ["Assumed 'the job' means the nightly batch, not an ad-hoc rerun."],
        }
    )

    with patch("s3_enhancement.analyze.complete", return_value=canned) as mock_complete:
        impact = draft_adhoc_impact_analysis("Fix the recurring timeout in the job.")

    assert mock_complete.call_args.kwargs["json_mode"] is True
    assert impact.text == "Likely touches BillingGateway's recalculation job."
    assert impact.assumptions == [
        "Assumed 'the job' means the nightly batch, not an ad-hoc rerun."
    ]
