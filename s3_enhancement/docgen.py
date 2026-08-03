"""S3 docs and release-note drafting.

This is narrative-only output and stays on the blocking `complete()` cache path.
The streamed record/replay path is reserved for generated source and test files.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from common.llm import LLMError, complete
from s3_enhancement import targets
from s3_enhancement.targets import Target

SYSTEM_PROMPT = (
    "You are an AI engineering assistant supporting an application-maintenance "
    "team for MapleSure Insurance. Given a user story that has just been "
    "implemented and tested, write a short, customer-friendly release note plus "
    "a one-line doc blurb describing the new capability."
)

DESIGN_DOC_SYSTEM_PROMPT = (
    "You are an AI engineering assistant supporting an application-maintenance "
    "team for MapleSure Insurance. Given a user story whose code has just "
    "been generated and applied (but not yet tested), write a short internal "
    "design document that hands the change off to QA."
)


def build_prompt(story_text: str) -> str:
    return f"""User story (now implemented and tested):
{story_text}

Write:
1. A short release note (2-4 sentences) suitable for a client-facing change
   log, describing the new tier-upgrade capability in the plan portal.
2. A one-line doc blurb suitable for a user-guide "What's new" section.

Keep the tone plain and factual - no marketing language, this is an internal
AMS delivery note, not an ad."""


def build_design_doc_prompt(story_text: str) -> str:
    return f"""User story (code generated and applied, not yet tested):
{story_text}

Write a short internal design document, for handoff to QA, with these sections:
1. Summary - one or two sentences on what is changing and why.
2. Affected areas - which parts of the app this touches.
3. Risk areas - anything QA should pay special attention to (backward
   compatibility, data consistency, edge cases).
4. Suggested QA focus - 2-4 concrete things the test suite should cover.

Keep the tone plain and factual - this is an internal engineering-to-QA
handoff document, not marketing copy."""


def draft_release_notes(
    story_text: str, *, target: Target | None = None, usage_out: dict | None = None
) -> str:
    """Draft a short release note + doc blurb for the given user story text."""
    target = target or targets.get_target(None)
    return complete(
        build_prompt(story_text),
        system=SYSTEM_PROMPT,
        cache_key=target.cache_key("release_notes"),
        usage_out=usage_out,
    )


def draft_design_doc(
    story_text: str, *, target: Target | None = None, usage_out: dict | None = None
) -> str:
    """Draft a short internal design doc handing the applied change off to QA
    — sits between "apply" and "generate tests" in the pipeline, so the test
    suite is generated against a reviewed handoff artifact rather than only
    the raw user story text."""
    target = target or targets.get_target(None)
    return complete(
        build_design_doc_prompt(story_text),
        system=DESIGN_DOC_SYSTEM_PROMPT,
        cache_key=target.cache_key("design_doc"),
        usage_out=usage_out,
    )


# --- release notes, split by audience ---------------------------------------

RELEASE_NOTE_SET_SYSTEM_PROMPT = (
    "You are an AI engineering assistant supporting an application-maintenance "
    "team for MapleSure Insurance. Given a user story that has just been "
    "implemented and tested, write release notes for three different audiences. "
    "Return structured JSON only. No markdown fences, no prose outside the JSON."
)

_SECRET_RE = re.compile(
    r"(sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----)"
)
_FORBIDDEN = ("real client", ".env", "api_key", "api key")


@dataclass(frozen=True)
class ReleaseNoteSet:
    """One release, written three times for three readers.

    The single blob this replaces mixed a client-facing note and a user-guide
    blurb in one text field, which meant whoever needed one of them had to
    edit the other out by hand. They go to different places — a changelog, a
    runbook, a help page — so they are separate fields.
    """

    changelog: str
    ops_note: str
    whats_new: str

    def to_dict(self) -> dict:
        return {
            "changelog": self.changelog,
            "ops_note": self.ops_note,
            "whats_new": self.whats_new,
        }


def build_release_note_set_prompt(story_text: str, *, target: Target) -> str:
    return f"""User story (implemented, tested and being released):
{story_text}

Application: {target.display_name}

Write three separate release notes for three audiences.

1. `changelog` — 2-4 sentences for a client-facing change log. What changed,
   in business terms, from the plan sponsor's or support engineer's point of
   view. No file names, no class names, no marketing language.
2. `ops_note` — 2-4 sentences for the team that runs this application. What
   changes operationally: schema or data migration, configuration, anything
   that must be deployed in a particular order, and how to tell quickly if
   the release went wrong. If none of those apply, say so plainly rather
   than inventing risk.
3. `whats_new` — one sentence for a user-guide "What's new" entry, written
   for an end user.

Plain and factual throughout — this is an internal AMS delivery record, not
an advertisement. Never invent a date, a version number or a ticket
reference that is not in the user story above.

Return structured JSON only, with this exact shape:
{{"changelog": "...", "ops_note": "...", "whats_new": "..."}}"""


def _parse_note_set(response: str) -> ReleaseNoteSet:
    text = response.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMError(f"Release notes response was not valid JSON: {response[:200]!r}") from exc
    if not isinstance(data, dict):
        raise LLMError("Release notes response must be a JSON object")

    fields = {}
    for name in ("changelog", "ops_note", "whats_new"):
        value = data.get(name)
        if not isinstance(value, str) or not value.strip():
            raise LLMError(f"Release notes response is missing {name!r}")
        cleaned = value.strip()
        lowered = cleaned.lower()
        for forbidden in _FORBIDDEN:
            if forbidden in lowered:
                raise LLMError(f"Release note {name!r} contains forbidden string {forbidden!r}")
        if _SECRET_RE.search(cleaned):
            raise LLMError(f"Release note {name!r} contains secret-shaped content")
        fields[name] = cleaned
    return ReleaseNoteSet(**fields)


def draft_release_note_set(
    story_text: str, *, target: Target | None = None, usage_out: dict | None = None
) -> ReleaseNoteSet:
    """Draft the three audience-specific release notes for `story_text`.

    A separate cache beat from `draft_release_notes`, not a replacement of it:
    the older call returns a plain string and is still reachable from the
    legacy /release-notes endpoint and the rehearsal scripts. Sharing a cache
    key would mean replay handing JSON to a caller expecting prose, or the
    reverse — common/llm.py keys on the literal, not the response shape.
    """
    target = target or targets.get_target(None)
    response = complete(
        build_release_note_set_prompt(story_text, target=target),
        system=RELEASE_NOTE_SET_SYSTEM_PROMPT,
        json_mode=True,
        cache_key=target.cache_key("release_note_set"),
        usage_out=usage_out,
    )
    return _parse_note_set(response)
