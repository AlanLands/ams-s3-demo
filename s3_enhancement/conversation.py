"""Shared multi-turn conversation primitives for S3's clarification-gated LLM
features (quick-impact chat, ad-hoc user story clarity check, and any future one).

Kept in its own module, separate from both callers, because quick_chat.py
already depends on analyze.py (for `EffortEstimate`) — putting this here
instead of in either module avoids a circular import between them.
"""

from __future__ import annotations

from dataclasses import dataclass

# A conversational feature may ask at most this many follow-up questions
# before it must produce a final answer — see
# docs/design/s3_llm_cost_controls.md rule 1. Enforced server-side by each
# caller counting prior assistant turns, never left to model discretion.
MAX_CLARIFICATION_TURNS = 2


@dataclass(frozen=True)
class ConversationTurn:
    role: str  # "user" | "assistant"
    text: str


def clarification_turns_used(history: list[ConversationTurn]) -> int:
    """How many clarifying questions have already been asked in this
    conversation — shared by every caller that needs to enforce
    `MAX_CLARIFICATION_TURNS` against a `ConversationTurn` history, including
    callers combining more than one question source (e.g. story-text vagueness
    and repo identity) against the same shared budget."""
    return sum(1 for turn in history if turn.role == "assistant")
