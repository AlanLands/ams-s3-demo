"""Resolve which registered `Target` a CR belongs to, from the CR text alone.

Every CR under `crs/*.md` now lives in one place, outside every target's own
directory (see CLAUDE.md's "File paths are load-bearing" section — moving a
*target's source* is a two-part rewrite; moving the CR text itself carries no
such cost, since `relevance.py`'s discovery globs only `*.py`/`*.java` and
never scores the CR text). That move only pays off if picking the right
target no longer depends on where the file sits, or on a human writing down
a ticket-key -> target_id mapping by hand — otherwise the coupling just moved
from the filesystem into a hardcoded table somewhere else. This module is
that missing piece: given a CR's text, find its target the same way
`applications.py` finds an application from a CI — deterministically first,
an LLM only when the deterministic tiers have no answer.

Three tiers, cheapest first:

1. **CR identifier.** Every CR opens with a `CR-YYYY-NNN:` title line, and
   every registered target's `cr_template_path.stem` is exactly that
   identifier (`CR-2026-041`, etc.) — a target IS the file it was registered
   with, so this is an exact structural match, not a guess. This is also the
   only tier that already works for today's three pinned CRs with zero
   registry lookups.
2. **`Application:` header.** Every CR also states which application it's
   for (`Application: ClaimsPortal (...)`). Matched against
   `applications.py`'s registered `display_name`s, then narrowed to that
   application's registered targets via `targets.targets_for_application()`.
   Resolves cleanly only when exactly one target is registered for that
   application — `applications.py`'s own docstring already notes an
   application can host more than one target (PolicyCore hosts two), so an
   ambiguous header falls through rather than guessing.
3. **AI fallback**, for a CR whose title isn't yet any registered target's
   `cr_template_path.stem` and whose `Application:` header is missing,
   misspelled, or ambiguous between targets — e.g. a genuinely new CR being
   drafted before its target is registered. Mirrors `repo_match.py`'s
   shape (`RepoMatch`-style result, the same confidence gate) but the
   candidate pool is this console's own registered targets, not a caller's
   GitLab projects.

Onboarding a new repo is then: register its `Target` (own `root`,
`cr_template_path`, `application_id`) in `targets.py`, drop its CR under
`crs/`. Tier 1 picks it up immediately — no ticket-key table to edit anywhere
else in this codebase.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from common.llm import LLMError, complete, parse_json_response
from s3_enhancement import applications, targets
from s3_enhancement.targets import Target

_TITLE_RE = re.compile(r"^(CR-\d{4}-\d+):", re.MULTILINE)
_APPLICATION_RE = re.compile(r"^Application:\s*(.+)$", re.MULTILINE)

MatchMethod = Literal["cr_id", "application_header", "ai", "unresolved"]

SYSTEM_PROMPT = (
    "You are an AI engineering assistant helping an application-maintenance team "
    "figure out which of their internally registered code targets a change request "
    "belongs to, given only each target's name and the change it already implements "
    "— you have not read any source code."
)


@dataclass(frozen=True)
class RankedCandidate:
    """One target the AI tier considered, with how strongly it fit.

    `score` is the model's own 0-100 rating, not a probability and not
    comparable across runs — it exists so a reviewer can see *what else was
    in the running and how close it came*, which is the difference between
    "the AI picked this" and "the AI picked this over that". Only ever
    populated for `method == "ai"`; the deterministic tiers rank nothing
    because they never compared anything.
    """

    target_id: str
    display_name: str
    score: int
    reasoning: str = ""


@dataclass(frozen=True)
class TargetMatch:
    """One resolution outcome, carrying how it was reached.

    `target is None` means every tier came up empty — the caller's next move
    is the same as an unrouted ticket: hand it to a human, don't guess past
    this point. `confidence`/`reasoning` are only meaningful for `method ==
    "ai"`; the deterministic tiers don't have a confidence to report because
    they never guessed.
    """

    target: Target | None
    method: MatchMethod
    confidence: str = "high"
    reasoning: str = ""
    # Every candidate the AI tier weighed, best first. Empty for the
    # deterministic tiers, and empty for an AI response that omitted or
    # malformed its ranking — a missing ranking degrades the explanation,
    # never the match itself.
    ranking: tuple[RankedCandidate, ...] = ()

    @property
    def resolved(self) -> bool:
        return self.target is not None

    @property
    def needs_confirmation(self) -> bool:
        """Same rule as `repo_match.needs_confirmation`: only a deterministic
        match or a high-confidence AI guess is trusted outright."""
        return self.method == "ai" and self.confidence != "high"


def _cr_id_from_text(cr_text: str) -> str | None:
    match = _TITLE_RE.search(cr_text)
    return match.group(1) if match else None


def _application_name_from_text(cr_text: str) -> str | None:
    match = _APPLICATION_RE.search(cr_text)
    if not match:
        return None
    # Header reads e.g. "PolicyCore (policy/claims portal)" — the parenthetical
    # is a human-readable gloss, not part of the name to match on.
    return match.group(1).split("(")[0].strip()


def _match_by_cr_id(cr_text: str) -> Target | None:
    cr_id = _cr_id_from_text(cr_text)
    if not cr_id:
        return None
    for target in targets.all_targets():
        if target.cr_template_path is not None and target.cr_template_path.stem == cr_id:
            return target
    return None


def _match_by_application_header(cr_text: str) -> Target | None:
    name = _application_name_from_text(cr_text)
    if not name:
        return None
    matches = [
        app for app in applications.all_applications()
        if app.display_name.lower() == name.lower()
    ]
    if len(matches) != 1:
        return None
    candidates = targets.targets_for_application(matches[0].app_id)
    return candidates[0] if len(candidates) == 1 else None


def _describe_target(target: Target) -> str:
    title = target.display_name
    if target.cr_template_path is not None and target.cr_template_path.exists():
        cr_id = target.cr_template_path.stem
        title = f"{target.display_name} ({cr_id})"
    return f"target_id={target.target_id}: {title}"


def build_ai_prompt(cr_text: str, candidates: tuple[Target, ...]) -> str:
    listing = "\n".join(_describe_target(target) for target in candidates)
    return f"""Change request:
{cr_text}

Candidate internal targets:
{listing}

Which target_id is this change request most likely for? Base this only on the
target descriptions above.

Rank every candidate listed, including the ones you reject — a reviewer needs
to see what else was in the running and how close it came, not just the
winner.

Return JSON exactly matching:
{{
  "target_id": "the id of the single most likely target, as a string",
  "confidence": "high, medium, or low",
  "reasoning": "one sentence explaining the match",
  "ranking": [
    {{
      "target_id": "candidate id",
      "score": 0-100 how well this candidate fits, as a number,
      "reasoning": "a few words on why it scored there"
    }}
  ]
}}"""


def _match_by_ai(cr_text: str) -> TargetMatch:
    candidates = targets.all_targets()
    if not candidates:
        return TargetMatch(target=None, method="unresolved")

    try:
        response = complete(
            build_ai_prompt(cr_text, candidates),
            system=SYSTEM_PROMPT,
            json_mode=True,
        )
        data = parse_json_response(response, required_keys={"target_id"})
    except LLMError:
        # Same posture as analyze_adhoc's repo-match call: an LLM hiccup here
        # degrades to "unresolved", not a 502 for the whole analysis.
        return TargetMatch(target=None, method="unresolved")

    by_id = {target.target_id: target for target in candidates}
    picked = by_id.get(str(data["target_id"]))
    if picked is None:
        return TargetMatch(target=None, method="unresolved")

    return TargetMatch(
        target=picked,
        method="ai",
        confidence=str(data.get("confidence", "medium")),
        reasoning=str(data.get("reasoning", "")),
        ranking=_parse_ranking(data.get("ranking"), by_id),
    )


def _parse_ranking(raw: object, by_id: dict[str, Target]) -> tuple[RankedCandidate, ...]:
    """Parse the model's ranked candidate list, defensively.

    Everything here is best-effort: a malformed or missing ranking costs the
    card its explanation, never the match. Entries naming a target that isn't
    a real candidate are dropped rather than rendered — a ranking row for a
    repo this console doesn't have would be a confident-looking fabrication.
    """
    if not isinstance(raw, list):
        return ()
    ranked: list[RankedCandidate] = []
    seen: set[str] = set()
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        target_id = str(entry.get("target_id", ""))
        target = by_id.get(target_id)
        if target is None or target_id in seen:
            continue
        seen.add(target_id)
        try:
            score = int(float(entry.get("score", 0)))
        except (TypeError, ValueError):
            score = 0
        ranked.append(
            RankedCandidate(
                target_id=target_id,
                display_name=target.display_name,
                score=max(0, min(100, score)),
                reasoning=str(entry.get("reasoning", "")),
            )
        )
    ranked.sort(key=lambda candidate: candidate.score, reverse=True)
    return tuple(ranked)


def resolve_target_for_cr(cr_text: str) -> TargetMatch:
    """Resolve `cr_text` to a registered `Target`, cheapest tier first."""
    by_id = _match_by_cr_id(cr_text)
    if by_id is not None:
        return TargetMatch(target=by_id, method="cr_id")

    by_header = _match_by_application_header(cr_text)
    if by_header is not None:
        return TargetMatch(target=by_header, method="application_header")

    return _match_by_ai(cr_text)
