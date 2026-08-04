"""S3 adapter — pure narrative, no threshold.

"Failure" is structural breakage (provider error, degenerate output, an obvious
refusal, or release notes collapsed into one clause) — the same criteria as
tools/verify_s3_live.py, not LLM-graded narrative quality (grading with another LLM
would reintroduce the exact non-determinism this tooling exists to eliminate).

Note on live edits: `draft_impact_analysis`/`draft_release_notes` each read
`SYSTEM_PROMPT` from their own module's globals at call time, so a plain module-level
attribute assignment (not `importlib.reload`) is enough to make a mid-run fix take
effect immediately — see the `_sync_*` helpers below.
"""

from __future__ import annotations

import s3_enhancement.analyze as analyze_module
import s3_enhancement.docgen as docgen_module
from common.llm import LLMError
from s3_enhancement.analyze import draft_effort_estimate, draft_impact_analysis
from s3_enhancement.story import render_story
from s3_enhancement.docgen import draft_release_notes
from tools.autofix.loop import LiveCheckSpec, ScenarioAdapter
from tools.autofix.splice import read_target
from tools.autofix.targets import REGISTRY

_REFUSAL_MARKERS = ("as an ai", "i cannot", "i'm sorry, but", "i am unable to")
_MIN_LENGTH = 40
_CR_TEXT = render_story("Elite")


def _assert_structurally_sound(text: str, label: str) -> None:
    if len(text.strip()) < _MIN_LENGTH:
        raise AssertionError(f"{label}: degenerate output ({len(text.strip())} chars)")
    lowered = text.lower()
    for marker in _REFUSAL_MARKERS:
        if marker in lowered:
            raise AssertionError(f"{label}: looks like a refusal (contains {marker!r})")


def _has_two_distinguishable_parts(text: str) -> bool:
    sentence_count = sum(text.count(ch) for ch in ".!?")
    has_marker = any(marker in text for marker in ("1.", "2.", "- ", "* ", "\n\n"))
    return sentence_count >= 2 and has_marker


def _sync_effort_estimate_prompt() -> None:
    analyze_module.EFFORT_SYSTEM_PROMPT = read_target(
        REGISTRY["s3.effort_estimate.system_prompt"]
    )


def _sync_impact_analysis_prompt() -> None:
    analyze_module.IMPACT_SYSTEM_PROMPT = read_target(
        REGISTRY["s3.impact_analysis.system_prompt"]
    )


def _sync_release_notes_prompt() -> None:
    docgen_module.SYSTEM_PROMPT = read_target(REGISTRY["s3.release_notes.system_prompt"])


def _effort_estimate_trial_fn() -> None:
    _sync_effort_estimate_prompt()
    try:
        estimate = draft_effort_estimate(_CR_TEXT)
    except LLMError as exc:
        raise AssertionError(f"effort estimate: LLMError: {exc}") from exc
    if not estimate.hours_class.strip():
        raise AssertionError("effort estimate: empty hours_class")
    if estimate.priority_equivalent not in ("P1", "P2", "P3", "P4"):
        raise AssertionError(
            f"effort estimate: priority_equivalent={estimate.priority_equivalent!r} "
            "not one of P1-P4"
        )


def _impact_analysis_trial_fn() -> None:
    _sync_impact_analysis_prompt()
    try:
        text = draft_impact_analysis(_CR_TEXT)
    except LLMError as exc:
        raise AssertionError(f"impact analysis: LLMError: {exc}") from exc
    _assert_structurally_sound(text, "impact analysis")


def _release_notes_trial_fn() -> None:
    _sync_release_notes_prompt()
    try:
        text = draft_release_notes(_CR_TEXT)
    except LLMError as exc:
        raise AssertionError(f"release notes: LLMError: {exc}") from exc
    _assert_structurally_sound(text, "release notes")
    if not _has_two_distinguishable_parts(text):
        raise AssertionError(
            "release notes: collapsed into a single clause, expected the "
            "release-note + doc-blurb parts asked for in the prompt"
        )


def build_adapter() -> ScenarioAdapter:
    checks = [
        LiveCheckSpec(
            name="effort estimate structurally sound",
            trial_fn=_effort_estimate_trial_fn,
            eligible_targets=["s3.effort_estimate.system_prompt"],
        ),
        LiveCheckSpec(
            name="impact analysis structurally sound",
            trial_fn=_impact_analysis_trial_fn,
            eligible_targets=["s3.impact_analysis.system_prompt"],
        ),
        LiveCheckSpec(
            name="release notes structurally sound",
            trial_fn=_release_notes_trial_fn,
            eligible_targets=["s3.release_notes.system_prompt"],
        ),
    ]
    return ScenarioAdapter(scenario="s3", checks=checks)
