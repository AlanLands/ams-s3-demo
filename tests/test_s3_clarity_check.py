import json
from unittest.mock import patch

import pytest

from common.llm import LLMError
from s3_enhancement.analyze import MAX_CLARIFICATION_TURNS, check_cr_clarity
from s3_enhancement.conversation import ConversationTurn


def test_check_cr_clarity_asks_a_question_for_a_vague_ticket():
    canned = json.dumps({"needs_clarification": True, "question": "Which report is slow?"})
    with patch("s3_enhancement.analyze.complete", return_value=canned) as mock_complete:
        result = check_cr_clarity("fix the thing")

    assert mock_complete.call_args.kwargs["json_mode"] is True
    assert result.needs_clarification is True
    assert result.question == "Which report is slow?"


def test_check_cr_clarity_passes_through_a_specific_ticket():
    canned = json.dumps({"needs_clarification": False})
    with patch("s3_enhancement.analyze.complete", return_value=canned):
        result = check_cr_clarity(
            "Add a 'Priority' field (Standard/Urgent) to the endorsement request form, "
            "defaulting to Standard."
        )

    assert result.needs_clarification is False
    assert result.question == ""


def test_check_cr_clarity_enforces_the_turn_cap():
    """Same cap as quick_chat.py's needs_clarification pattern (see
    docs/design/s3_llm_cost_controls.md rule 1) - a model that tries to ask a
    third question after the cap is a prompt bug, not a valid response."""
    history = [
        ConversationTurn(role="user", text="fix the thing"),
        ConversationTurn(role="assistant", text="Which app is this against?"),
        ConversationTurn(role="user", text="the portal"),
        ConversationTurn(role="assistant", text="Which part of the portal?"),
    ]
    assert sum(1 for t in history if t.role == "assistant") == MAX_CLARIFICATION_TURNS

    canned = json.dumps({"needs_clarification": True, "question": "One more thing?"})
    with patch("s3_enhancement.analyze.complete", return_value=canned):
        with pytest.raises(LLMError):
            check_cr_clarity("still vague", history)


def test_check_cr_clarity_rejects_empty_question():
    canned = json.dumps({"needs_clarification": True, "question": ""})
    with patch("s3_enhancement.analyze.complete", return_value=canned):
        with pytest.raises(LLMError):
            check_cr_clarity("fix the thing")
