"""S3 AI-assisted intake analysis and effort sizing.

These calls intentionally keep using `common.llm.complete()` rather than the
streaming S3 codegen path. They are short narrative/JSON drafts that do not
touch the filesystem, so the generic `.cache/llm` cache remains the right
reliability mechanism; only the long file-generation step needs streamed,
recordable output.
"""

from __future__ import annotations

from dataclasses import dataclass

from common.llm import LLMError, complete, parse_json_response
from s3_enhancement import relevance, targets
from s3_enhancement.targets import Target

IMPACT_SYSTEM_PROMPT = (
    "You are an AI engineering assistant supporting an application-maintenance "
    "team for MapleSure Insurance. Given a change request and the current source "
    "of a small mock policy/claims app, write a short, practical impact analysis "
    "for the support engineer who will review the CR before work starts."
)

EFFORT_SYSTEM_PROMPT = (
    "You are an AI engineering assistant supporting an application-maintenance team "
    "for MapleSure Insurance. Given a change request, size it before work starts: "
    "roughly how many engineer-hours it would take, and an equivalent incident "
    "priority (P1-P4) for scheduling purposes - this is a rough sizing signal for "
    "the support lead deciding when to slot the work in, not a committed estimate."
)

@dataclass(frozen=True)
class EffortEstimate:
    hours_class: str
    priority_equivalent: str
    reasoning: str


def _read_codebase_context(cr_text: str, *, target: Target | None = None) -> str:
    """Read the target's source files relevant to this CR, as prompt context."""
    target = target or targets.get_target(None)
    all_files = relevance.discover_files_for_target(target, cr_text)
    selection = relevance.select_relevant_files(cr_text, all_files, core_files=target.core_files)
    sections = [
        f"--- {rel_path} ---\n{content}"
        for rel_path, content in selection.selected.items()
    ]
    return "\n\n".join(sections)


def build_impact_prompt(cr_text: str, *, target: Target | None = None) -> str:
    return f"""Change request:
{cr_text}

Current codebase context:
{_read_codebase_context(cr_text, target=target)}

Write a short impact analysis (roughly 5-10 lines) covering:
1. What files/functions need to change to implement this CR.
2. What risk areas exist (e.g. schema/data migration, premium calculation
   correctness, effect on existing flows).
3. What should be tested before this ships.

Keep it concise and practical - this is read by a support engineer deciding
whether to approve the CR for build, not a formal spec document."""


def build_effort_prompt(cr_text: str) -> str:
    return f"""Change request:
{cr_text}

Size this CR before work starts. Return JSON exactly matching:
{{
  "hours_class": "an approximate hour-class estimate, e.g. '~40h'",
  "priority_equivalent": "P1, P2, P3, or P4 - equivalent scheduling priority",
  "reasoning": "one or two sentences explaining the estimate"
}}"""


def draft_impact_analysis(
    cr_text: str, *, target: Target | None = None, usage_out: dict | None = None
) -> str:
    """Draft a short impact analysis for the given CR text."""
    target = target or targets.get_target(None)
    return complete(
        build_impact_prompt(cr_text, target=target),
        system=IMPACT_SYSTEM_PROMPT,
        cache_key=target.cache_key("impact_analysis"),
        usage_out=usage_out,
    )


def draft_effort_estimate(
    cr_text: str, *, target: Target | None = None, usage_out: dict | None = None
) -> EffortEstimate:
    """Draft an effort estimate for the given CR text."""
    target = target or targets.get_target(None)
    response = complete(
        build_effort_prompt(cr_text),
        system=EFFORT_SYSTEM_PROMPT,
        json_mode=True,
        cache_key=target.cache_key("effort_estimate"),
        usage_out=usage_out,
    )
    data = parse_json_response(response, required_keys={"hours_class", "priority_equivalent"})
    try:
        return EffortEstimate(
            hours_class=str(data["hours_class"]),
            priority_equivalent=str(data["priority_equivalent"]).upper(),
            reasoning=str(data.get("reasoning", "")),
        )
    except (TypeError, ValueError) as exc:
        raise LLMError(f"effort estimate response had unexpected field types: {exc}") from exc
