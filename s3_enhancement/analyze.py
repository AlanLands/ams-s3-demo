"""S3 AI-assisted intake analysis and effort sizing.

These calls intentionally keep using `common.llm.complete()` rather than the
streaming S3 codegen path. They are short narrative/JSON drafts that do not
touch the filesystem, so the generic `.cache/llm` cache remains the right
reliability mechanism; only the long file-generation step needs streamed,
recordable output.
"""

from __future__ import annotations

from dataclasses import dataclass

from common.constants import APPLICATIONS
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

ADHOC_IMPACT_SYSTEM_PROMPT = (
    "You are an AI engineering assistant supporting an application-maintenance "
    "team for MapleSure Insurance. This ticket is for an application this "
    "console has no source access to (e.g. it was raised for another team). "
    "Given only the ticket's own text, write a short, practical impact analysis "
    "for the support engineer who will scope the work - general terms, no "
    "invented file or function names since you cannot see that codebase."
)

CROSS_TEAM_SYSTEM_PROMPT = (
    "You are an AI engineering assistant supporting an application-maintenance "
    "team for MapleSure Insurance. Given a change request and its codebase "
    "context, identify whether any OTHER application team (not the one this "
    "CR is already filed against) would also need to do work because of this "
    "change - e.g. a downstream consumer of data this CR changes, a shared "
    "data contract, or a document/notification another system generates. "
    "Only flag a team if there is a concrete, specific reason; most small CRs "
    "affect no other team, and an empty list is a normal, correct answer."
)


@dataclass(frozen=True)
class EffortEstimate:
    hours_class: str
    priority_equivalent: str
    reasoning: str


@dataclass(frozen=True)
class CrossTeamImpact:
    app_name: str
    reason: str
    suggested_summary: str


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


def build_adhoc_impact_prompt(cr_text: str) -> str:
    """Unlike `build_impact_prompt`, no codebase context — this is for a
    ticket this console has no target/source for (e.g. a cross-team ticket
    raised against another application)."""
    return f"""Ticket:
{cr_text}

You have no source access to the application this ticket is against. Write a
short impact analysis (roughly 5-10 lines) covering:
1. What's likely involved to implement this, in general terms.
2. What risk areas to expect (e.g. schema/data migration, correctness,
   effect on existing flows).
3. What should be tested before this ships.

Keep it concise and practical - this is read by a support engineer deciding
how to scope the work, not a formal spec document."""


def build_effort_prompt(cr_text: str) -> str:
    return f"""Change request:
{cr_text}

Size this CR before work starts. Return JSON exactly matching:
{{
  "hours_class": "an approximate hour-class estimate, e.g. '~40h'",
  "priority_equivalent": "P1, P2, P3, or P4 - equivalent scheduling priority",
  "reasoning": "one or two sentences explaining the estimate"
}}"""


def build_cross_team_prompt(cr_text: str, *, target: Target | None = None) -> str:
    apps = ", ".join(APPLICATIONS)
    return f"""Change request:
{cr_text}

Current codebase context:
{_read_codebase_context(cr_text, target=target)}

The known application landscape (do not invent other app names): {apps}

Identify zero or more OTHER applications (not the one this CR is already
filed against) that would also need work because of this change. Only
include an app if there's a concrete, specific reason from the codebase or CR
text above — most small CRs affect no other team, so an empty list is a
normal, correct answer.

Return JSON exactly matching:
{{
  "impacts": [
    {{
      "app_name": "<one of the known application names above, never the CR's own app>",
      "reason": "<one sentence, specific to this CR>",
      "suggested_summary": "<one-line Jira ticket summary for that team>"
    }}
  ]
}}"""


def draft_cross_team_impact(
    cr_text: str, *, target: Target | None = None, usage_out: dict | None = None
) -> list[CrossTeamImpact]:
    """Identify other application teams that would also need to do work
    because of this CR, e.g. a downstream consumer or shared data contract."""
    target = target or targets.get_target(None)
    response = complete(
        build_cross_team_prompt(cr_text, target=target),
        system=CROSS_TEAM_SYSTEM_PROMPT,
        json_mode=True,
        cache_key=target.cache_key("cross_team_impact"),
        usage_out=usage_out,
    )
    data = parse_json_response(response, required_keys={"impacts"})
    impacts = data["impacts"]
    if not isinstance(impacts, list):
        raise LLMError("cross-team impact response's 'impacts' was not a list")

    results: list[CrossTeamImpact] = []
    for item in impacts:
        if not isinstance(item, dict):
            raise LLMError("cross-team impact entries must be objects")
        app_name = str(item.get("app_name", ""))
        if app_name not in APPLICATIONS:
            raise LLMError(
                f"cross-team impact named an unknown application {app_name!r}; "
                f"expected one of {APPLICATIONS}"
            )
        results.append(
            CrossTeamImpact(
                app_name=app_name,
                reason=str(item.get("reason", "")),
                suggested_summary=str(item.get("suggested_summary", "")),
            )
        )
    return results


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


def _parse_effort_estimate_response(response: str) -> EffortEstimate:
    data = parse_json_response(response, required_keys={"hours_class", "priority_equivalent"})
    try:
        return EffortEstimate(
            hours_class=str(data["hours_class"]),
            priority_equivalent=str(data["priority_equivalent"]).upper(),
            reasoning=str(data.get("reasoning", "")),
        )
    except (TypeError, ValueError) as exc:
        raise LLMError(f"effort estimate response had unexpected field types: {exc}") from exc


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
    return _parse_effort_estimate_response(response)


def draft_adhoc_impact_analysis(cr_text: str, *, usage_out: dict | None = None) -> str:
    """Impact analysis for a ticket with no linked target/codebase in this
    console (e.g. a cross-team ticket for another application) — same shape
    as `draft_impact_analysis`, but skips codebase context entirely rather
    than dumping an unrelated target's files into the prompt.

    No fixed `cache_key`, unlike the pinned-CR beats above: there's no single
    "the" ad-hoc ticket to pre-record for a demo rehearsal, so this caches by
    content hash instead (`common.llm.complete`'s default when no cache_key is
    given) — safe because it never collides with a differently-worded ticket.
    """
    return complete(
        build_adhoc_impact_prompt(cr_text),
        system=ADHOC_IMPACT_SYSTEM_PROMPT,
        usage_out=usage_out,
    )


def draft_adhoc_effort_estimate(cr_text: str, *, usage_out: dict | None = None) -> EffortEstimate:
    """Effort estimate for an ad-hoc ticket — see `draft_adhoc_impact_analysis`
    for why no target/cache_key is involved."""
    response = complete(
        build_effort_prompt(cr_text),
        system=EFFORT_SYSTEM_PROMPT,
        json_mode=True,
        usage_out=usage_out,
    )
    return _parse_effort_estimate_response(response)
