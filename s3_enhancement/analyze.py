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
from s3_enhancement.conversation import MAX_CLARIFICATION_TURNS, ConversationTurn
from s3_enhancement.targets import Target

IMPACT_SYSTEM_PROMPT = (
    "You are an AI engineering assistant supporting an application-maintenance "
    "team for MapleSure Insurance. Given a user story and the current source "
    "of a small mock policy/claims app, write a short, practical impact analysis "
    "for the support engineer who will review the user story before work starts."
)

EFFORT_SYSTEM_PROMPT = (
    "You are an AI engineering assistant supporting an application-maintenance team "
    "for MapleSure Insurance. Given a user story, size it before work starts: "
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

CLARITY_SYSTEM_PROMPT = (
    "You are an AI engineering assistant supporting an application-maintenance "
    "team for MapleSure Insurance, screening a ticket before impact analysis "
    "runs. Decide whether the ticket text is specific enough to analyze "
    "responsibly, or so vague/generic that impact analysis would likely be "
    "misdirected at the wrong area. If genuinely unclear, ask ONE short "
    "clarifying question. Most tickets are clear enough - an empty need for "
    "clarification is the normal, correct answer; do not ask a question just "
    "to be thorough."
)

GAP_SYSTEM_PROMPT = (
    "You are an AI engineering assistant supporting an application-maintenance "
    "team for MapleSure Insurance, screening a user story that has already "
    "passed a general clarity check, for a specific missing detail that would "
    "otherwise force you to silently guess: an unstated numeric threshold, "
    "percentage, or amount; an unstated eligibility/scope criterion (who or "
    "what this applies to); an unstated field name, data type, or default "
    "value; an unstated target system or module. If you find one such gap, ask "
    "ONE short clarifying question about it - naming the specific field or "
    "value that's missing - instead of proceeding on a guess. Most user stories specify "
    "enough on all of these dimensions - an empty need for clarification is "
    "the normal, correct answer; do not ask about a detail that's genuinely "
    "inferable or conventional (e.g. defaulting a boolean flag to false needs "
    "no question)."
)

CROSS_TEAM_SYSTEM_PROMPT = (
    "You are an AI engineering assistant supporting an application-maintenance "
    "team for MapleSure Insurance. Given a user story and its codebase "
    "context, identify whether any OTHER application team (not the one this "
    "user story is already filed against) would also need to do work because of this "
    "change - e.g. a downstream consumer of data this user story changes, a shared "
    "data contract, or a document/notification another system generates. "
    "Only flag a team if there is a concrete, specific reason; most small user stories "
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


@dataclass(frozen=True)
class ClarityResult:
    needs_clarification: bool
    question: str = ""


@dataclass(frozen=True)
class ImpactAnalysis:
    text: str
    # One sentence per gap the model had to fill in rather than ask about —
    # e.g. an unstated field name, an assumed default, an assumed scope
    # boundary. Surfaced separately from `text` so a reviewer sees each
    # assumption as its own falsifiable line item instead of prose it could
    # read past. Empty when the user story left nothing unspecified. This exists
    # because the clarity check (ClarityResult above) only catches a ticket
    # too vague to analyze *at all* — a ticket with some detail but a gap in
    # one dimension sails through (or exhausts the clarification-turn cap)
    # and the model fills that gap silently unless told to declare it here.
    assumptions: list[str]


def _read_codebase_context(story_text: str, *, target: Target | None = None) -> str:
    """Read the target's source files relevant to this user story, as prompt context."""
    target = target or targets.get_target(None)
    all_files = relevance.discover_files_for_target(target, story_text)
    selection = relevance.select_relevant_files(
        story_text, all_files, core_files=target.core_files, design_doc_root=target.root
    )
    sections = [
        f"--- {rel_path} ---\n{content}"
        for rel_path, content in selection.selected.items()
    ]
    return "\n\n".join(sections)


_ASSUMPTIONS_INSTRUCTION = """Before writing the analysis, check specifically for these
commonly-missing specifics: any unstated numeric threshold, percentage, or
amount; any unstated eligibility/scope criterion (who or what this applies
to); any unstated field name, data type, or default value; any unstated
target system or module. Writing the analysis in general terms to route
around a gap (e.g. "modify the relevant logic" instead of naming what the
request never specified) is exactly the failure mode this is guarding
against - it hides the same gap behind vaguer language instead of
surfacing it. If the request doesn't pin one of these down and your
analysis has to proceed on a specific reading anyway, that reading is an
assumption: name it as a separate, one-sentence assumption, not as prose in
the analysis.

Two things are NOT assumptions and must never appear in the list: (1)
anything the request already states explicitly - restating a given
requirement back as an "assumption" is misleading, not helpful, even if
it's paraphrased; (2) a normal inference about the existing codebase (e.g.
that a field needs to be added to both a model and its schema, or how an
existing table is structured) that the provided codebase context already
answers or that you'd verify by reading the code rather than by asking the
requester. Only list something here if it is a genuine external unknown -
about the request's intent, not the code - that neither the request nor
the codebase context resolves. An empty assumptions list is only correct
when the request actually leaves nothing like this open - do not invent
one otherwise, and do not leave the list empty just because the analysis
reads smoothly.

Return structured JSON only, exactly matching:
{
  "impact_analysis": "<the analysis text, roughly 5-10 lines>",
  "assumptions": ["<one sentence per assumption you had to make>"]
}"""


def build_impact_prompt(story_text: str, *, target: Target | None = None) -> str:
    return f"""User story:
{story_text}

Current codebase context:
{_read_codebase_context(story_text, target=target)}

Write a short impact analysis (roughly 5-10 lines) covering:
1. What files/functions need to change to implement this user story.
2. What risk areas exist (e.g. schema/data migration, contribution calculation
   correctness, effect on existing flows).
3. What should be tested before this ships.

Keep it concise and practical - this is read by a support engineer deciding
whether to approve the user story for build, not a formal spec document.

{_ASSUMPTIONS_INSTRUCTION}"""


def build_adhoc_impact_prompt(story_text: str) -> str:
    """Unlike `build_impact_prompt`, no codebase context — this is for a
    ticket this console has no target/source for (e.g. a cross-team ticket
    raised against another application)."""
    return f"""Ticket:
{story_text}

You have no source access to the application this ticket is against. Write a
short impact analysis (roughly 5-10 lines) covering:
1. What's likely involved to implement this, in general terms.
2. What risk areas to expect (e.g. schema/data migration, correctness,
   effect on existing flows).
3. What should be tested before this ships.

Keep it concise and practical - this is read by a support engineer deciding
how to scope the work, not a formal spec document.

{_ASSUMPTIONS_INSTRUCTION}"""


def _parse_impact_analysis_response(response: str) -> ImpactAnalysis:
    data = parse_json_response(response, required_keys={"impact_analysis"})
    assumptions = data.get("assumptions", [])
    if not isinstance(assumptions, list):
        raise LLMError("impact analysis response's 'assumptions' was not a list")
    return ImpactAnalysis(
        text=str(data["impact_analysis"]),
        assumptions=[str(item) for item in assumptions],
    )


def build_effort_prompt(story_text: str) -> str:
    return f"""User story:
{story_text}

Size this user story before work starts. Return JSON exactly matching:
{{
  "hours_class": "an approximate hour-class estimate, e.g. '~40h'",
  "priority_equivalent": "P1, P2, P3, or P4 - equivalent scheduling priority",
  "reasoning": "one or two sentences explaining the estimate"
}}"""


def build_cross_team_prompt(story_text: str, *, target: Target | None = None) -> str:
    apps = ", ".join(APPLICATIONS)
    return f"""User story:
{story_text}

Current codebase context:
{_read_codebase_context(story_text, target=target)}

The known application landscape (do not invent other app names): {apps}

Identify zero or more OTHER applications (not the one this user story is already
filed against) that would also need work because of this change. Only
include an app if there's a concrete, specific reason from the codebase or user story
text above — most small user stories affect no other team, so an empty list is a
normal, correct answer.

Return JSON exactly matching:
{{
  "impacts": [
    {{
      "app_name": "<one of the known application names above, never the user story's own app>",
      "reason": "<one sentence, specific to this user story>",
      "suggested_summary": "<one-line Jira ticket summary for that team>"
    }}
  ]
}}"""


def draft_cross_team_impact(
    story_text: str, *, target: Target | None = None, usage_out: dict | None = None
) -> list[CrossTeamImpact]:
    """Identify other application teams that would also need to do work
    because of this user story, e.g. a downstream consumer or shared data contract."""
    target = target or targets.get_target(None)
    response = complete(
        build_cross_team_prompt(story_text, target=target),
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
    story_text: str,
    *,
    target: Target | None = None,
    usage_out: dict | None = None,
    pin_cache: bool = True,
) -> ImpactAnalysis:
    """Draft a short impact analysis for the given user story text, plus any
    assumptions the model had to make to write it (see `ImpactAnalysis`).

    `pin_cache=False` drops the fixed per-target `cache_key` and lets
    `complete()` cache by prompt hash instead. Callers re-drafting after an
    engineer answered a clarifying question MUST pass it: the pinned key
    ignores prompt content entirely (that's the point of it — one recorded
    response per demo beat, every rehearsal), so a re-draft would otherwise
    replay the pre-answer analysis verbatim and keep reporting the very
    assumption the engineer just resolved.
    """
    target = target or targets.get_target(None)
    response = complete(
        build_impact_prompt(story_text, target=target),
        system=IMPACT_SYSTEM_PROMPT,
        json_mode=True,
        cache_key=target.cache_key("impact_analysis") if pin_cache else None,
        usage_out=usage_out,
    )
    return _parse_impact_analysis_response(response)


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
    story_text: str,
    *,
    target: Target | None = None,
    usage_out: dict | None = None,
    pin_cache: bool = True,
) -> EffortEstimate:
    """Draft an effort estimate for the given user story text. See
    `draft_impact_analysis` for when `pin_cache=False` is required."""
    target = target or targets.get_target(None)
    response = complete(
        build_effort_prompt(story_text),
        system=EFFORT_SYSTEM_PROMPT,
        json_mode=True,
        cache_key=target.cache_key("effort_estimate") if pin_cache else None,
        usage_out=usage_out,
    )
    return _parse_effort_estimate_response(response)


def _clarification_turns_used(history: list[ConversationTurn]) -> int:
    return sum(1 for turn in history if turn.role == "assistant")


def build_clarity_prompt(story_text: str, history: list[ConversationTurn]) -> str:
    cap_note = ""
    if _clarification_turns_used(history) >= MAX_CLARIFICATION_TURNS:
        cap_note = (
            "\nYou have already asked the maximum allowed number of clarifying "
            "questions for this ticket - you MUST answer needs_clarification: "
            "false now, even if some detail is still unclear; a human will "
            "proceed with the best available reading of the ticket."
        )
    transcript = "\n".join(f"{turn.role}: {turn.text}" for turn in history)
    return f"""Ticket, plus any follow-up exchanged so far:
{transcript or "(no follow-up yet)"}

Latest ticket text: {story_text}
{cap_note}

Return structured JSON only, exactly one of these two shapes:
{{"needs_clarification": true, "question": "<one short question>"}}
{{"needs_clarification": false}}"""


def check_story_clarity(
    story_text: str,
    history: list[ConversationTurn] | None = None,
    *,
    usage_out: dict | None = None,
) -> ClarityResult:
    """Screen an ad-hoc ticket for vagueness before impact analysis runs, at
    most `MAX_CLARIFICATION_TURNS` clarifying questions (see
    docs/design/s3_llm_cost_controls.md) - same needs_clarification/cap
    pattern as `quick_chat.continue_session`, reused via `conversation.py`.

    No target/codebase context: this only judges the ticket text's own
    specificity, the same scope `draft_adhoc_impact_analysis` already
    operates in - nothing to scope with `relevance.select_relevant_files`.
    """
    history = history or []
    response = complete(
        build_clarity_prompt(story_text, history),
        system=CLARITY_SYSTEM_PROMPT,
        json_mode=True,
        usage_out=usage_out,
    )
    data = parse_json_response(response, required_keys={"needs_clarification"})
    if data["needs_clarification"]:
        if _clarification_turns_used(history) >= MAX_CLARIFICATION_TURNS:
            raise LLMError(
                "adhoc clarity check tried to ask a clarifying question past the "
                f"{MAX_CLARIFICATION_TURNS}-turn cap - treat as a bug in the prompt, "
                "not a valid model response"
            )
        question = str(data.get("question", "")).strip()
        if not question:
            raise LLMError("clarity check needs_clarification=true but no question was given")
        return ClarityResult(needs_clarification=True, question=question)
    return ClarityResult(needs_clarification=False)


def build_gap_prompt(story_text: str, history: list[ConversationTurn]) -> str:
    cap_note = ""
    if _clarification_turns_used(history) >= MAX_CLARIFICATION_TURNS:
        cap_note = (
            "\nYou have already asked the maximum allowed number of clarifying "
            "questions for this user story - you MUST answer needs_clarification: "
            "false now, even if a gap remains; a human will proceed with the "
            "best available reading, noted as an assumption in the analysis."
        )
    transcript = "\n".join(f"{turn.role}: {turn.text}" for turn in history)
    return f"""User story, plus any follow-up exchanged so far:
{transcript or "(no follow-up yet)"}

Latest user story text: {story_text}
{cap_note}

Return structured JSON only, exactly one of these two shapes:
{{"needs_clarification": true, "question": "<one short question about the missing detail>"}}
{{"needs_clarification": false}}"""


def check_story_gaps(
    story_text: str,
    history: list[ConversationTurn] | None = None,
    *,
    usage_out: dict | None = None,
) -> ClarityResult:
    """Screen a user story that has already passed the overall clarity check (see
    `check_story_clarity`) for a specific missing detail — an unstated default,
    threshold, or scope boundary — that the final analysis would otherwise
    have to silently guess and report back as an assumption (see
    `ImpactAnalysis.assumptions`). Same needs_clarification/cap pattern and
    turn budget as `check_story_clarity`; callers run both against the same
    shared history so the two gates share one conversational budget rather
    than doubling `MAX_CLARIFICATION_TURNS`.

    Runs on user story text alone, no codebase context — the categories of gap this
    catches (numeric thresholds, eligibility criteria, field defaults, target
    systems) are business decisions, not something source code would answer.
    """
    history = history or []
    response = complete(
        build_gap_prompt(story_text, history),
        system=GAP_SYSTEM_PROMPT,
        json_mode=True,
        usage_out=usage_out,
    )
    data = parse_json_response(response, required_keys={"needs_clarification"})
    if data["needs_clarification"]:
        if _clarification_turns_used(history) >= MAX_CLARIFICATION_TURNS:
            raise LLMError(
                "gap check tried to ask a clarifying question past the "
                f"{MAX_CLARIFICATION_TURNS}-turn cap - treat as a bug in the prompt, "
                "not a valid model response"
            )
        question = str(data.get("question", "")).strip()
        if not question:
            raise LLMError("gap check needs_clarification=true but no question was given")
        return ClarityResult(needs_clarification=True, question=question)
    return ClarityResult(needs_clarification=False)


def build_assumption_question(assumptions: list[str]) -> str:
    """Turn the assumptions a drafted analysis had to make into one clarifying
    question back to the engineer.

    This is the gate that actually closes the "ask, don't assume" loop.
    `check_story_gaps` runs *before* the analysis and can only predict what the
    model might have to guess at — it screens the user story text alone and routinely
    disagrees with what the draft then assumes (either passing a user story the
    analysis goes on to guess about, or asking about a detail the user story already
    states). This runs on the draft's own declared assumptions, so what gets
    asked is exactly what would otherwise have been guessed.

    Every assumption goes into a single question rather than one question
    each: `MAX_CLARIFICATION_TURNS` is a hard budget shared with the other
    gates, so asking them one-per-turn would silently drop the rest.

    No LLM call — the assumption sentences are already the model's own words,
    so wrapping them deterministically keeps this free and keeps a rehearsed
    demo replaying identically.
    """
    if not assumptions:
        raise ValueError("build_assumption_question called with no assumptions")
    if len(assumptions) == 1:
        return (
            "Before I finalise the analysis — this isn't specified, so I'd "
            f"otherwise assume: {assumptions[0]}\n\n"
            "Is that right? If not, tell me what it should be."
        )
    numbered = "\n".join(f"{i}. {item}" for i, item in enumerate(assumptions, start=1))
    return (
        "Before I finalise the analysis — these aren't specified, so I'd "
        f"otherwise assume:\n\n{numbered}\n\n"
        "Are those right? If not, tell me what they should be."
    )


def draft_adhoc_impact_analysis(
    story_text: str, *, usage_out: dict | None = None
) -> ImpactAnalysis:
    """Impact analysis for a ticket with no linked target/codebase in this
    console (e.g. a cross-team ticket for another application) — same shape
    as `draft_impact_analysis`, but skips codebase context entirely rather
    than dumping an unrelated target's files into the prompt.

    No fixed `cache_key`, unlike the pinned-user story beats above: there's no single
    "the" ad-hoc ticket to pre-record for a demo rehearsal, so this caches by
    content hash instead (`common.llm.complete`'s default when no cache_key is
    given) — safe because it never collides with a differently-worded ticket.
    """
    response = complete(
        build_adhoc_impact_prompt(story_text),
        system=ADHOC_IMPACT_SYSTEM_PROMPT,
        json_mode=True,
        usage_out=usage_out,
    )
    return _parse_impact_analysis_response(response)


def draft_adhoc_effort_estimate(story_text: str, *, usage_out: dict | None = None) -> EffortEstimate:
    """Effort estimate for an ad-hoc ticket — see `draft_adhoc_impact_analysis`
    for why no target/cache_key is involved."""
    response = complete(
        build_effort_prompt(story_text),
        system=EFFORT_SYSTEM_PROMPT,
        json_mode=True,
        usage_out=usage_out,
    )
    return _parse_effort_estimate_response(response)
