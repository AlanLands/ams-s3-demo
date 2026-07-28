"""S3 quick-impact chat — a free-text "how much would this cost me" entry
point, separate from the fixed CR-2026-041/042 flow.

Asks at most `MAX_CLARIFICATION_TURNS` clarifying questions when it needs
more detail, then returns an impact analysis and effort/priority estimate
shaped like `s3_enhancement.analyze.EffortEstimate` so the frontend can reuse
its existing renderer. See docs/design/s3_llm_cost_controls.md for the cost
rules this module must follow (capped turns, scoped context, transcript-hash
caching) — do not relax any of them when extending this module.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from common.llm import LLMError, complete, parse_json_response
from s3_enhancement import relevance, targets
from s3_enhancement.analyze import EffortEstimate
from s3_enhancement.conversation import MAX_CLARIFICATION_TURNS, ConversationTurn
from s3_enhancement.targets import Target

# Re-exported under this module's original name — `analyze.py`'s ad-hoc
# clarity check shares the same turn shape (see s3_enhancement/conversation.py)
# but callers importing `QuickChatTurn` from here are unaffected.
QuickChatTurn = ConversationTurn

SYSTEM_PROMPT = (
    "You are an AI engineering assistant supporting an application-maintenance "
    "team for MapleSure Insurance. A support engineer or manager is asking a "
    "free-text question about a hypothetical change to a small mock "
    "policy/claims app, before any formal change request exists. If you "
    "genuinely need more detail to size the change, ask ONE short clarifying "
    "question. Otherwise, give a final answer: a short impact analysis, an "
    "effort/priority estimate, and whether a concrete code change is "
    "warranted right now versus just an estimate."
)


@dataclass(frozen=True)
class QuickChatResult:
    needs_clarification: bool
    question: str = ""
    impact_analysis: str = ""
    effort_estimate: EffortEstimate | None = None
    code_change_warranted: bool = False
    suggested_cr_summary: str = ""


def _clarification_turns_used(history: list[QuickChatTurn]) -> int:
    return sum(1 for turn in history if turn.role == "assistant")


def _read_codebase_context(message: str, *, target: Target) -> str:
    """Scoped codebase context — same discovery/selection path analyze.py's
    fixed-CR impact analysis uses, never a raw whole-repo dump."""
    all_files = relevance.discover_files_for_target(target, message)
    selection = relevance.select_relevant_files(
        message, all_files, core_files=target.core_files, design_doc_root=target.root
    )
    return "\n\n".join(
        f"--- {rel_path} ---\n{content}" for rel_path, content in selection.selected.items()
    )


def _build_prompt(message: str, history: list[QuickChatTurn], *, target: Target) -> str:
    cap_note = ""
    if _clarification_turns_used(history) >= MAX_CLARIFICATION_TURNS:
        cap_note = (
            "\nYou have already asked the maximum allowed number of clarifying "
            "questions for this conversation — you MUST give a final answer now, "
            "no more questions, even if some detail is still unclear; make a "
            "reasonable assumption and say so in the impact analysis."
        )

    transcript = "\n".join(f"{turn.role}: {turn.text}" for turn in history)
    json_shapes = """If you need one clarifying question and have not hit the cap above:
{"needs_clarification": true, "question": "<one short question>"}

Otherwise, your final answer:
{
  "needs_clarification": false,
  "impact_analysis": "<3-6 lines: what would change, risk areas, what to test>",
  "hours_class": "an approximate hour-class estimate, e.g. '~4h'",
  "priority_equivalent": "P1, P2, P3, or P4",
  "reasoning": "one or two sentences explaining the estimate",
  "code_change_warranted": true or false,
  "suggested_cr_summary": "<one line summarizing this as a CR, or empty>"
}"""

    return f"""Conversation so far:
{transcript or "(nothing yet)"}

Latest message: {message}
{cap_note}

Current codebase context (scoped to what looks relevant to this question):
{_read_codebase_context(message, target=target)}

Return structured JSON only, exactly one of these two shapes:

{json_shapes}"""


def continue_session(
    message: str,
    history: list[QuickChatTurn],
    *,
    target: Target | None = None,
    usage_out: dict | None = None,
) -> QuickChatResult:
    """Continue (or start, with an empty `history`) a quick-impact chat
    session.

    `history` is the full prior transcript — the cache key hashes the whole
    transcript (not just the latest message) so a rehearsed conversation
    replays deterministically turn-by-turn under `LLM_MODE=replay`.
    """
    target = target or targets.get_target(None)
    prompt = _build_prompt(message, history, target=target)

    transcript_key_material = (
        "\n".join(f"{turn.role}:{turn.text}" for turn in history) + f"\nuser:{message}"
    )
    digest = hashlib.sha256(transcript_key_material.encode("utf-8")).hexdigest()[:16]

    response = complete(
        prompt,
        system=SYSTEM_PROMPT,
        json_mode=True,
        cache_key=f"s3_quick_chat:{digest}",
        usage_out=usage_out,
    )
    data = parse_json_response(response, required_keys={"needs_clarification"})

    if data["needs_clarification"]:
        if _clarification_turns_used(history) >= MAX_CLARIFICATION_TURNS:
            raise LLMError(
                "quick chat tried to ask a clarifying question past the "
                f"{MAX_CLARIFICATION_TURNS}-turn cap — treat as a bug in the prompt, not a "
                "valid model response"
            )
        question = str(data.get("question", "")).strip()
        if not question:
            raise LLMError("quick chat needs_clarification=true but no question was given")
        return QuickChatResult(needs_clarification=True, question=question)

    required = {"impact_analysis", "hours_class", "priority_equivalent"}
    missing = required - data.keys()
    if missing:
        raise LLMError(f"quick chat final answer missing required keys {sorted(missing)}")

    return QuickChatResult(
        needs_clarification=False,
        impact_analysis=str(data["impact_analysis"]),
        effort_estimate=EffortEstimate(
            hours_class=str(data["hours_class"]),
            priority_equivalent=str(data["priority_equivalent"]).upper(),
            reasoning=str(data.get("reasoning", "")),
        ),
        code_change_warranted=bool(data.get("code_change_warranted", False)),
        suggested_cr_summary=str(data.get("suggested_cr_summary", "")),
    )
