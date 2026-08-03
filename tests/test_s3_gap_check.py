import json
from unittest.mock import patch

import pytest

from common.llm import LLMError
from s3_enhancement.analyze import MAX_CLARIFICATION_TURNS, check_cr_gaps
from s3_enhancement.conversation import ConversationTurn


def test_check_cr_gaps_asks_about_an_unstated_default():
    canned = json.dumps(
        {
            "needs_clarification": True,
            "question": "What should the 'priority' field default to if not specified?",
        }
    )
    with patch("s3_enhancement.analyze.complete", return_value=canned) as mock_complete:
        result = check_cr_gaps(
            "Add a 'priority' field (Standard/Urgent) to the amendment request form."
        )

    assert mock_complete.call_args.kwargs["json_mode"] is True
    assert result.needs_clarification is True
    assert "default" in result.question.lower()


def test_check_cr_gaps_passes_through_a_fully_specified_cr():
    canned = json.dumps({"needs_clarification": False})
    with patch("s3_enhancement.analyze.complete", return_value=canned):
        result = check_cr_gaps(
            "Add a 'priority' field (Standard/Urgent) to the amendment request form, "
            "defaulting to Standard."
        )

    assert result.needs_clarification is False
    assert result.question == ""


def test_check_cr_gaps_enforces_the_turn_cap():
    history = [
        ConversationTurn(role="user", text=""),
        ConversationTurn(role="assistant", text="What should the default be?"),
        ConversationTurn(role="user", text="Standard"),
        ConversationTurn(role="assistant", text="Which roles can override it?"),
    ]
    assert sum(1 for t in history if t.role == "assistant") == MAX_CLARIFICATION_TURNS

    canned = json.dumps({"needs_clarification": True, "question": "One more thing?"})
    with patch("s3_enhancement.analyze.complete", return_value=canned):
        with pytest.raises(LLMError):
            check_cr_gaps("still has a gap", history)


def test_check_cr_gaps_rejects_empty_question():
    canned = json.dumps({"needs_clarification": True, "question": ""})
    with patch("s3_enhancement.analyze.complete", return_value=canned):
        with pytest.raises(LLMError):
            check_cr_gaps("Add a 'priority' field.")
