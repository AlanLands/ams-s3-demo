"""LLM-driven fix proposal for one failing check against one registered FixTarget.

One `common.llm.complete()` call, fed the current value, the aggregated failure
detail, concrete failing examples, and this run's prior attempts on the same target
so it doesn't repeat a dead end. Returns a full replacement string (not a diff — a
diff invites escaping ambiguity when mechanically spliced into a Python literal).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from common.llm import complete, parse_json_response
from tools.autofix.targets import FixTarget

SYSTEM_PROMPT = (
    "You are calibrating one specific text constant in a demo application-"
    "maintenance tool. You may propose a replacement for exactly one named string. "
    "You must not propose changes to any other file, code structure, or the JSON "
    "response contract it governs. Return strict JSON matching the requested shape. "
    "`new_value` must be a complete replacement for the entire string, not a diff "
    "or patch, and must not contain '{' or '}' characters — this string is not an "
    "f-string template."
)


@dataclass(frozen=True)
class PriorAttempt:
    value: str
    outcome: str


@dataclass(frozen=True)
class FailureContext:
    scenario: str
    check_name: str
    detail: str
    target: FixTarget
    current_value: str
    worst_trial_examples: list[str] = field(default_factory=list)
    prior_attempts: list[PriorAttempt] = field(default_factory=list)


@dataclass(frozen=True)
class FixProposal:
    target_id: str
    new_value: str
    rationale: str


def _build_prompt(ctx: FailureContext) -> str:
    examples_block = (
        "\n".join(f"- {example}" for example in ctx.worst_trial_examples[:3])
        or "(no examples captured)"
    )
    attempts_block = (
        "\n".join(
            f"- attempt: {attempt.value!r}\n  outcome: {attempt.outcome}"
            for attempt in ctx.prior_attempts
        )
        or "(no prior attempts this run)"
    )

    return f"""Scenario: {ctx.scenario}
Failing check: {ctx.check_name}
Failure detail: {ctx.detail}

Target: {ctx.target.id}
What this string is for: {ctx.target.description}

Current value:
---
{ctx.current_value}
---

Worst-case examples from the failing trials:
{examples_block}

Prior attempts on this target in this run — do not repeat these verbatim:
{attempts_block}

You may only change this one value. Do not suggest edits to any other file or
field. Propose a full replacement string (max {ctx.target.max_chars} characters,
no '{{' or '}}' characters) that would make the failing check pass, while staying
consistent with the rest of this file's style and purpose.

Return JSON exactly matching this shape:
{{
  "new_value": "the complete replacement string",
  "rationale": "one or two sentences explaining the change"
}}"""


def propose_fix(ctx: FailureContext, *, run_id: str, iteration: int) -> FixProposal:
    response = complete(
        _build_prompt(ctx),
        system=SYSTEM_PROMPT,
        json_mode=True,
        cache_key=f"autofix:{run_id}:{iteration}:{ctx.target.id}",
    )
    data = parse_json_response(response, required_keys={"new_value"})
    return FixProposal(
        target_id=ctx.target.id,
        new_value=str(data["new_value"]),
        rationale=str(data.get("rationale", "")),
    )


def validate_proposal(proposal: FixProposal, target: FixTarget, current_value: str) -> str | None:
    """Return an error message if `proposal` is unsafe to apply, else None."""
    if proposal.target_id != target.id:
        return f"proposal target_id {proposal.target_id!r} does not match {target.id!r}"
    if not proposal.new_value.strip():
        return "proposed new_value is empty"
    if len(proposal.new_value) > target.max_chars:
        return f"proposed new_value is {len(proposal.new_value)} chars, max is {target.max_chars}"
    if "{" in proposal.new_value or "}" in proposal.new_value:
        return "proposed new_value contains '{' or '}' — not allowed, this is not an f-string"
    if proposal.new_value == current_value:
        return "proposed new_value is identical to the current value — no-op"
    return None
