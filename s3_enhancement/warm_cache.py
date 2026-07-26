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
from s3_enhancement.cr import raw_cr_template, render_cr
from s3_enhancement.docgen import draft_design_doc, draft_release_notes
from s3_enhancement.testgen import generate_tests


def warm(tier_name: str = "Elite") -> list[str]:
    messages = []
    for target in targets.all_targets():
        # GitLab-sourced targets are read-only discovery/relevance previews
        # (see targets.py's module docstring) with no local CR template to
        # render narrative drafts against — nothing to warm. Registry-only
        # test fixtures can likewise lack a template; skip both rather than
        # crash on a target this function was never meant to cover.
        if target.cr_template_path is None:
            continue
        cr_text = render_cr(tier_name, target=target)
        draft_effort_estimate(cr_text, target=target)
        draft_impact_analysis(cr_text, target=target)
        draft_design_doc(cr_text, target=target)
        draft_release_notes(cr_text, target=target)
        messages.append(f"narrative cache warmed for {target.target_id}")
    return messages


def record(tier_name: str = "Elite") -> list[str]:
    template = raw_cr_template()
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
