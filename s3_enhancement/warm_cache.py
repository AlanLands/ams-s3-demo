"""Pre-warm S3 LLM caches.

`warm()` populates the generic `.cache/llm` store used by short narrative
drafts. `record()` runs the live streamed generators once with `LLM_MODE=record`
so `s3_enhancement/cache/*.json` can be replayed during the stage demo.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from s3_enhancement.analyze import draft_effort_estimate, draft_impact_analysis
from s3_enhancement.codegen import generate_change
from s3_enhancement.cr import raw_cr_template, render_cr
from s3_enhancement.docgen import draft_release_notes
from s3_enhancement.testgen import generate_tests


def warm(tier_name: str = "Elite") -> list[str]:
    cr_text = render_cr(tier_name)
    draft_effort_estimate(cr_text)
    draft_impact_analysis(cr_text)
    draft_release_notes(cr_text)
    return ["effort estimate warmed", "impact analysis warmed", "release notes warmed"]


def record(tier_name: str = "Elite") -> list[str]:
    rendered = render_cr(tier_name)
    template = raw_cr_template()
    with _temporary_env("LLM_MODE", "record"):
        draft_effort_estimate(rendered)
        draft_impact_analysis(rendered)
        generate_change(tier_name, template)
        generate_tests(tier_name, template)
        draft_release_notes(rendered)
    return [
        "effort estimate warmed",
        "impact analysis warmed",
        "codegen replay recorded",
        "testgen replay recorded",
        "release notes warmed",
    ]


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
