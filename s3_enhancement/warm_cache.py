"""Pre-warm S3 LLM caches.

`warm()` populates the generic `.cache/llm` store used by short narrative
drafts, for every registered target — not just the default one. Each target's
`draft_*` calls use a target-scoped `cache_key` (see `targets.Target.cache_key`),
so warming the default target alone leaves every other target's narrative
beats (design doc, release notes, effort/impact) a guaranteed cold call on
first live use after a reset, since `demo/reset_s3.sh` wipes `.cache/llm`
every rehearsal. `record()` runs the live streamed generators once with
`LLM_MODE=record` so `s3_enhancement/cache/*.json` can be replayed during the
stage demo — this one still only covers the default target's codegen/testgen
streamed beats; the other targets' streamed replay caches are pre-recorded
and committed directly (see `demo/DEMO_TEST_GUIDE.md`).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from s3_enhancement import targets
from s3_enhancement.analyze import draft_effort_estimate, draft_impact_analysis
from s3_enhancement.codegen import generate_change
from s3_enhancement.story import raw_story_template, render_story
from s3_enhancement.docgen import (
    draft_design_doc,
    draft_release_note_set,
    draft_release_notes,
)
from s3_enhancement.scenarios import draft_scenarios
from s3_enhancement.target_match import resolve_target_for_story
from s3_enhancement.testgen import generate_tests


def _warm_target_resolution() -> list[str]:
    """Warm `/s3/target/resolve` for every user story under `stories/`.

    Only the AI tier costs anything — a user story whose title matches a registered
    target's `story_template_path.stem`, or whose `Application:` header narrows
    to exactly one target, resolves deterministically with no model call, so
    calling this for every user story warms precisely the ones that need it.

    Without this the AI tier is a guaranteed cold call on stage:
    `demo/reset_s3.sh` wipes `.cache/llm` every rehearsal, and
    `target_match._match_by_ai` caches by content hash (no pinned
    `cache_key`), so its entry lives in that wiped directory rather than the
    committed `s3_enhancement/cache/`. A cold call there does not fail
    loudly either — `_match_by_ai` swallows `LLMError` into an `unresolved`
    match, which the console would show as "couldn't identify the repo".
    """
    messages = []
    stories_root = targets.REPO_ROOT / "stories"
    for story_path in sorted(stories_root.glob("*.md")):
        match = resolve_target_for_story(story_path.read_text(encoding="utf-8"))
        messages.append(
            f"{story_path.name} -> {match.target.target_id if match.resolved else 'unresolved'}"
            f" via {match.method}"
        )
    return messages


def warm(tier_name: str = "Elite") -> list[str]:
    messages = _warm_target_resolution()
    for target in targets.all_targets():
        # GitLab-sourced targets are read-only discovery/relevance previews
        # (see targets.py's module docstring) with no local user story template to
        # render narrative drafts against — nothing to warm. Registry-only
        # test fixtures can likewise lack a template; skip both rather than
        # crash on a target this function was never meant to cover.
        if target.story_template_path is None:
            continue
        story_text = render_story(tier_name, target=target)
        draft_effort_estimate(story_text, target=target)
        draft_impact_analysis(story_text, target=target)
        draft_design_doc(story_text, target=target)
        draft_release_notes(story_text, target=target)
        draft_release_note_set(story_text, target=target)
        draft_scenarios(story_text, target=target)
        messages.append(f"narrative cache warmed for {target.target_id}")
    return messages


def record(tier_name: str = "Elite") -> list[str]:
    template = raw_story_template()
    with _temporary_env("LLM_MODE", "record"):
        generate_change(tier_name, template)
        generate_tests(tier_name, template)
    messages = ["codegen replay recorded", "testgen replay recorded"]
    messages.extend(warm(tier_name))
    return messages


def main() -> None:
    for line in warm():
        print(line)


@contextmanager
def _temporary_env(name: str, value: str) -> Iterator[None]:
    old = os.environ.get(name)
    os.environ[name] = value
    try:
        yield
    finally:
        if old is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = old


if __name__ == "__main__":
    main()
