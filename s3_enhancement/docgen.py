"""S3 docs and release-note drafting.

This is narrative-only output and stays on the blocking `complete()` cache path.
The streamed record/replay path is reserved for generated source and test files.
"""

from __future__ import annotations

from common.llm import complete
from s3_enhancement import targets
from s3_enhancement.targets import Target

SYSTEM_PROMPT = (
    "You are an AI engineering assistant supporting an application-maintenance "
    "team for MapleSure Insurance. Given a change request that has just been "
    "implemented and tested, write a short, customer-friendly release note plus "
    "a one-line doc blurb describing the new capability."
)

DESIGN_DOC_SYSTEM_PROMPT = (
    "You are an AI engineering assistant supporting an application-maintenance "
    "team for MapleSure Insurance. Given a change request whose code has just "
    "been generated and applied (but not yet tested), write a short internal "
    "design document that hands the change off to QA."
)


def build_prompt(cr_text: str) -> str:
    return f"""Change request (now implemented and tested):
{cr_text}

Write:
1. A short release note (2-4 sentences) suitable for a client-facing change
   log, describing the new coverage-upgrade capability in the policy portal.
2. A one-line doc blurb suitable for a user-guide "What's new" section.

Keep the tone plain and factual - no marketing language, this is an internal
AMS delivery note, not an ad."""


def build_design_doc_prompt(cr_text: str) -> str:
    return f"""Change request (code generated and applied, not yet tested):
{cr_text}

Write a short internal design document, for handoff to QA, with these sections:
1. Summary - one or two sentences on what is changing and why.
2. Affected areas - which parts of the app this touches.
3. Risk areas - anything QA should pay special attention to (backward
   compatibility, data consistency, edge cases).
4. Suggested QA focus - 2-4 concrete things the test suite should cover.

Keep the tone plain and factual - this is an internal engineering-to-QA
handoff document, not marketing copy."""


def draft_release_notes(
    cr_text: str, *, target: Target | None = None, usage_out: dict | None = None
) -> str:
    """Draft a short release note + doc blurb for the given CR text."""
    target = target or targets.get_target(None)
    return complete(
        build_prompt(cr_text),
        system=SYSTEM_PROMPT,
        cache_key=target.cache_key("release_notes"),
        usage_out=usage_out,
    )


def draft_design_doc(
    cr_text: str, *, target: Target | None = None, usage_out: dict | None = None
) -> str:
    """Draft a short internal design doc handing the applied change off to QA
    — sits between "apply" and "generate tests" in the pipeline, so the test
    suite is generated against a reviewed handoff artifact rather than only
    the raw CR text."""
    target = target or targets.get_target(None)
    return complete(
        build_design_doc_prompt(cr_text),
        system=DESIGN_DOC_SYSTEM_PROMPT,
        cache_key=target.cache_key("design_doc"),
        usage_out=usage_out,
    )
