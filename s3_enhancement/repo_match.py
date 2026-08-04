"""AI-assisted repo matching for S3's GitLab beat.

When a user story arrives without a pre-selected target repo, this asks the LLM to
pick the most likely repo from the caller's connected GitLab projects, by
matching the user story text against each project's name/description — the automatic
alternative to manually choosing a `project_id` (see
api/routers/s3.py's `/gitlab/projects/{id}/scope`).

Unlike S3's demo-pinned narrative calls (analyze.py, docgen.py), this call's
input genuinely varies every time (the user story text and the caller's actual
project list), so it deliberately omits a fixed `cache_key` — `complete()`
then falls back to `common/llm.py`'s default content-hash cache, which is the
correct behavior for input that isn't the same every run (see
s3_enhancement/DESIGN_MULTI_REPO.md for why a fixed cache_key would be wrong
here).
"""

from __future__ import annotations

from dataclasses import dataclass

from common.llm import LLMError, complete, parse_json_response

SYSTEM_PROMPT = (
    "You are an AI engineering assistant helping an application-maintenance team "
    "figure out which of their repositories a user story applies to, given only "
    "each repository's name and description — you have not read any source code."
)


@dataclass(frozen=True)
class RepoMatch:
    project_id: str
    reasoning: str
    confidence: str = "medium"


@dataclass(frozen=True)
class RepoSuggestion:
    best_match: RepoMatch
    alternates: tuple[RepoMatch, ...]


def _describe(project: dict) -> str:
    name = project.get("name_with_namespace") or project.get("name") or "(unnamed)"
    description = project.get("description") or "(no description)"
    return f"id={project.get('id')}: {name} — {description}"


def build_prompt(story_text: str, projects: list[dict]) -> str:
    listing = "\n".join(_describe(project) for project in projects)
    return f"""User story:
{story_text}

Candidate repositories:
{listing}

Which repository is this user story most likely for? Base this only on the
repository names and descriptions above — you have not read any of their source code.

Return JSON exactly matching:
{{
  "best_match_id": "the id of the single most likely repository, as a string",
  "confidence": "high, medium, or low",
  "reasoning": "one sentence explaining the match",
  "alternates": [
    {{"id": "...", "reasoning": "one short sentence on why it's a plausible second choice"}}
  ]
}}
Only include an alternate if it's a genuinely plausible second choice — an empty
list is fine when there's one clear match."""


def needs_confirmation(match: RepoMatch) -> bool:
    """Whether this repo-match should be confirmed with the developer before
    scoping proceeds against it, rather than silently treated as settled fact.

    Only 'high' confidence is trusted outright — a wrong guess here would
    scope file discovery/codegen against the wrong repo, the same class of
    risk `analyze.py`'s story-text clarity gate guards against for vague
    tickets (see CLAUDE.md's requirement-clarity-gate rule).
    """
    return match.confidence != "high"


def build_confirmation_question(suggestion: RepoSuggestion, projects: list[dict]) -> str:
    """A short question for the developer to confirm (or override) an
    uncertain repo-match — the repo-identity analogue of the user story text
    clarity-gate question."""
    projects_by_id = {str(project.get("id")): project for project in projects}

    def _name(project_id: str) -> str:
        project = projects_by_id.get(project_id, {})
        return project.get("name_with_namespace") or project.get("name") or project_id

    best = suggestion.best_match
    question = (
        f"I'm only {best.confidence}-confidence this user story is for "
        f"'{_name(best.project_id)}' ({best.reasoning}). Is that the right repo?"
    )
    if suggestion.alternates:
        alt_names = ", ".join(f"'{_name(alt.project_id)}'" for alt in suggestion.alternates)
        question += f" Possible alternates: {alt_names}."
    return question


def suggest_target_repo(story_text: str, projects: list[dict]) -> RepoSuggestion:
    """Ask the LLM to pick the most likely repo for this user story from `projects`.

    Raises `LLMError` if there are no candidates, the response is malformed,
    or the model picks an id outside the candidate list.
    """
    if not projects:
        raise LLMError("no candidate repositories to match against")

    response = complete(
        build_prompt(story_text, projects),
        system=SYSTEM_PROMPT,
        json_mode=True,
    )
    data = parse_json_response(response, required_keys={"best_match_id"})

    known_ids = {str(project.get("id")) for project in projects}
    best_id = str(data["best_match_id"])
    if best_id not in known_ids:
        raise LLMError(
            f"model picked project id {best_id!r} not in the candidate list {sorted(known_ids)}"
        )

    best_match = RepoMatch(
        project_id=best_id,
        confidence=str(data.get("confidence", "medium")),
        reasoning=str(data.get("reasoning", "")),
    )
    alternates = tuple(
        RepoMatch(project_id=str(item["id"]), reasoning=str(item.get("reasoning", "")))
        for item in data.get("alternates", [])
        if isinstance(item, dict) and str(item.get("id")) in known_ids
    )
    return RepoSuggestion(best_match=best_match, alternates=alternates)
