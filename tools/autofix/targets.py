"""The narrow, pre-registered set of string constants tools/autofix is allowed to
edit. Deliberately just one shape — a named module-level string constant — not
arbitrary file edits. Anything not in this registry cannot be reached by the fix
loop.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class FixTarget:
    id: str
    file: Path
    kind: Literal["module_constant", "tuple_field"]
    description: str
    constant_name: str | None = None
    list_name: str | None = None
    tuple_index: int | None = None
    field_index: int | None = None
    max_chars: int = 4000


REGISTRY: dict[str, FixTarget] = {
    "s3.effort_estimate.system_prompt": FixTarget(
        id="s3.effort_estimate.system_prompt",
        file=REPO_ROOT / "s3_enhancement" / "analyze.py",
        kind="module_constant",
        description="S3 effort-estimate-on-intake drafting system prompt.",
        constant_name="EFFORT_SYSTEM_PROMPT",
    ),
    "s3.impact_analysis.system_prompt": FixTarget(
        id="s3.impact_analysis.system_prompt",
        file=REPO_ROOT / "s3_enhancement" / "analyze.py",
        kind="module_constant",
        description="S3 impact-analysis drafting system prompt.",
        constant_name="IMPACT_SYSTEM_PROMPT",
    ),
    "s3.release_notes.system_prompt": FixTarget(
        id="s3.release_notes.system_prompt",
        file=REPO_ROOT / "s3_enhancement" / "docgen.py",
        kind="module_constant",
        description="S3 release-notes drafting system prompt.",
        constant_name="SYSTEM_PROMPT",
    ),
}
