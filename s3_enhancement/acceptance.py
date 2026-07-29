"""Acceptance criteria, read out of a CR rather than inferred from it.

Deliberately not an LLM call. The criteria are already written down in the
change request; asking a model to restate them would add a paraphrase step
that can drift, and would make the traceability matrix's left-hand column an
AI artifact rather than the customer's own words. Same principle as the
routing panel's CI lookup: when the answer is in a table, read the table.

Every CR under `*/crs/*.md` shares one shape — a run of `Key: Value` headers,
prose sections, then an `Acceptance criteria:` heading over a flat list of
`- ` bullets, some with hard-wrapped continuation lines and (CR-2026-043)
nested sub-bullets that belong to the criterion above them. The list ends at
the first blank line; anything after that is a different section, which
matters because CR-2026-041 follows its criteria with a "Known downstream
considerations" list that is explicitly *not* in scope for that CR.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_HEADING_RE = re.compile(r"^\s*acceptance criteria\s*:\s*$", re.IGNORECASE)
_BULLET_RE = re.compile(r"^[-*]\s+(.*)$")
_INDENTED_RE = re.compile(r"^\s+\S")

# A criterion of the form "existing X keeps working / is unaffected" is a
# regression statement: it is satisfied by the app's pre-existing suite, not
# by anything the CR adds. Detected by wording rather than position because
# CRs put it last by convention, not by rule.
_REGRESSION_HINTS = (
    "unaffected",
    "keep working",
    "keeps working",
    "still succeeds",
    "as before",
    "without changes",
    "no changes to",
)


@dataclass(frozen=True)
class Criterion:
    """One acceptance criterion, numbered in the order the CR states it."""

    id: str
    text: str

    @property
    def is_regression(self) -> bool:
        lowered = self.text.lower()
        return any(hint in lowered for hint in _REGRESSION_HINTS)


def _flatten(lines: list[str]) -> str:
    """Join a criterion's wrapped lines back into one sentence.

    Nested sub-bullets keep their leading marker so a criterion that carries a
    structured contract (CR-2026-043's ClaimRules API) still reads as a list
    when rendered, rather than collapsing into an unpunctuated run-on.
    """
    parts: list[str] = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        sub_bullet = _BULLET_RE.match(stripped)
        if sub_bullet and index > 0:
            parts.append("• " + sub_bullet.group(1))
        else:
            parts.append(stripped)
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def parse_acceptance_criteria(cr_text: str) -> list[Criterion]:
    """Every acceptance criterion in `cr_text`, in CR order. Empty if the CR
    has no acceptance-criteria section — callers must handle that rather than
    assume, since an ad-hoc ticket has no CR at all."""
    lines = cr_text.replace("\r\n", "\n").split("\n")
    start: int | None = None
    for index, line in enumerate(lines):
        if _HEADING_RE.match(line):
            start = index + 1
            break
    if start is None:
        return []

    groups: list[list[str]] = []
    for line in lines[start:]:
        if not line.strip():
            break  # end of the section — a later list is a different section
        if _BULLET_RE.match(line):
            groups.append([line.strip()])
        elif groups and _INDENTED_RE.match(line):
            groups[-1].append(line)
        elif groups:
            groups[-1].append(line)
        # A non-bullet, non-indented first line means the section isn't a
        # list at all; skip it rather than inventing a criterion.

    criteria: list[Criterion] = []
    for index, group in enumerate(groups, start=1):
        bullet = _BULLET_RE.match(group[0])
        head = bullet.group(1) if bullet else group[0]
        text = _flatten([head, *group[1:]])
        if text:
            criteria.append(Criterion(id=f"AC-{index}", text=text))
    return criteria
