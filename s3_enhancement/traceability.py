"""Acceptance criterion -> scenario -> automated test -> result.

The matrix a QA lead asks for and this pipeline could not previously produce.
Each row is one acceptance criterion, in the CR's own words and order, with
the planned scenarios that cite it, the executed tests that appear to
implement those scenarios, and the result of actually running them.

## Why the scenario -> test link is matched, not asserted

Three of the four columns are exact. The criteria come from the CR text
(`acceptance.py`), the scenario -> criterion citations are validated model
output (`scenarios.py`), and the pass/fail comes from parsed JUnit XML
(`testrun.py`). Only "which test implements which scenario" has no ground
truth: the generated suite is served from a committed replay recording that
predates the scenario beat, so the tests were never named after the plan.

So this module matches on significant-token overlap and is deliberately
conservative about it. A match is only claimed when one test is clearly the
best fit — above an absolute floor *and* meaningfully ahead of the runner-up.
Ambiguity resolves to "not automated", never to a guess. Over-reporting
coverage is the one failure mode a traceability matrix must not have: an
unmatched row costs a sentence of explanation, whereas a wrongly matched row
tells a room full of auditors that a requirement is tested when it isn't.

## Regression criteria

A criterion asserting existing behaviour is unaffected (`Criterion.
is_regression`) is answered by the app's checked-in regression suite, not by
anything generated for this CR. Those rows are matched against the regression
run instead, which is why both runs are passed in separately.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from s3_enhancement.acceptance import Criterion
from s3_enhancement.scenarios import Scenario
from s3_enhancement.testrun import TestCase

# Words that carry no discriminating signal in a test name or scenario title.
# "existing" and "unaffected" are deliberately absent — they are the strongest
# available signal that something is a regression check.
_STOPWORDS = frozenset(
    """
    a an and are as at be by can check confirm ensure for from has have in is it its
    of on or should so than that the then this to validate verify was when which with
    test tests testing case cases scenario given
    """.split()
)

# Same-meaning tokens the two vocabularies spell differently: a scenario title
# is written by an analyst, a test name by a code generator.
_SYNONYMS = {
    "rejects": "reject",
    "rejected": "reject",
    "rejection": "reject",
    "accepts": "accept",
    "accepted": "accept",
    "acceptance": "accept",
    "calculates": "calculate",
    "calculation": "calculate",
    "recalculates": "recalculate",
    "recalculated": "recalculate",
    "persists": "persist",
    "persisted": "persist",
    "submits": "submit",
    "submitted": "submit",
    "submission": "submit",
    "submitting": "submit",
    "upgrades": "upgrade",
    "upgraded": "upgrade",
    "defaults": "default",
    "defaulting": "default",
    "errors": "error",
    "raises": "raise",
    "values": "value",
    "fields": "field",
    "flows": "flow",
    "claims": "claim",
    "policies": "policy",
    "tiers": "tier",
    "requests": "request",
    "amendments": "amendment",
    "limits": "limit",
    "deductibles": "deductible",
}

# Tuned against the three committed demo recordings. Containment (below) runs
# hotter than a Jaccard ratio would, so the floor is correspondingly high;
# MIN_SHARED stops a single generic token ("claim") from carrying a match, and
# MARGIN stops a near-tie from resolving to whichever test sorted first.
MATCH_FLOOR = 0.5
MATCH_MARGIN = 0.15
MIN_SHARED_TOKENS = 2

_SPLIT_RE = re.compile(r"[^a-z0-9]+")
_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def _tokens(text: str) -> set[str]:
    spaced = _CAMEL_RE.sub(" ", text)
    raw = [token for token in _SPLIT_RE.split(spaced.lower()) if token]
    normalised = {_SYNONYMS.get(token, token) for token in raw}
    return {token for token in normalised if token not in _STOPWORDS and len(token) > 2}


def _score(scenario_tokens: set[str], case: TestCase) -> float:
    """Containment, not Jaccard: what fraction of the *smaller* vocabulary the
    two share.

    A scenario title plus its expected result runs to a dozen significant
    tokens; a generated test name runs to three or four. Dividing by the union
    therefore caps a perfect pairing at around 0.3 and makes every real match
    indistinguishable from noise — measured against the committed recordings
    before this was changed. Containment asks the question that actually
    matters: is this short test name essentially a subset of what the scenario
    describes?
    """
    case_tokens = _tokens(f"{case.name} {case.description}")
    if not scenario_tokens or not case_tokens:
        return 0.0
    shared = scenario_tokens & case_tokens
    if len(shared) < MIN_SHARED_TOKENS:
        return 0.0
    return len(shared) / min(len(scenario_tokens), len(case_tokens))


def match_scenario(scenario: Scenario, cases: list[TestCase]) -> TestCase | None:
    """The one test that clearly implements `scenario`, or None.

    None is a legitimate, common answer: the scenario may be planned but not
    automated, automated in a suite not passed in here, or simply too close a
    call between two tests to claim either.
    """
    if not cases:
        return None
    scenario_tokens = _tokens(f"{scenario.title} {scenario.expected}")
    ranked = sorted(
        ((_score(scenario_tokens, case), case.name, case) for case in cases),
        key=lambda item: (item[0], item[1]),
        reverse=True,
    )
    best_score, _, best_case = ranked[0]
    if best_score < MATCH_FLOOR:
        return None
    if len(ranked) > 1 and best_score - ranked[1][0] < MATCH_MARGIN:
        return None
    return best_case


@dataclass
class MatrixRow:
    """One acceptance criterion's coverage, end to end."""

    criterion_id: str
    criterion_text: str
    is_regression: bool
    scenario_ids: list[str] = field(default_factory=list)
    test_names: list[str] = field(default_factory=list)
    # "passed" | "failed" | "not_automated" | "no_scenario" | "not_run"
    status: str = "no_scenario"
    # Which suite answers this row: "generated", "regression", or "".
    covered_by: str = ""

    def to_dict(self) -> dict:
        return {
            "criterion_id": self.criterion_id,
            "criterion_text": self.criterion_text,
            "is_regression": self.is_regression,
            "scenario_ids": self.scenario_ids,
            "test_names": self.test_names,
            "status": self.status,
            "covered_by": self.covered_by,
        }


@dataclass
class Matrix:
    rows: list[MatrixRow]

    @property
    def fully_covered(self) -> bool:
        return all(row.status == "passed" for row in self.rows)

    def summary(self) -> dict[str, int]:
        counts = {
            "total": len(self.rows),
            "passed": 0,
            "failed": 0,
            "not_automated": 0,
            "no_scenario": 0,
            "not_run": 0,
        }
        for row in self.rows:
            counts[row.status] = counts.get(row.status, 0) + 1
        return counts

    def to_dict(self) -> dict:
        return {"rows": [row.to_dict() for row in self.rows], "summary": self.summary()}


def _status_for(cases: list[TestCase]) -> str:
    if any(case.status in ("failed", "error") for case in cases):
        return "failed"
    if all(case.status == "skipped" for case in cases):
        return "not_run"
    return "passed"


def build_matrix(
    criteria: list[Criterion],
    scenarios: list[Scenario],
    *,
    generated_cases: list[TestCase] | None = None,
    regression_cases: list[TestCase] | None = None,
) -> Matrix:
    """Assemble the matrix from parts that were each produced independently.

    Either run may be absent — a matrix built before anything has been
    executed is still useful (it shows plan coverage), it just reports
    "not_run" rather than a result.
    """
    generated_cases = generated_cases or []
    regression_cases = regression_cases or []

    by_criterion: dict[str, list[Scenario]] = {criterion.id: [] for criterion in criteria}
    for scenario in scenarios:
        for ref in scenario.acceptance_criteria:
            if ref in by_criterion:
                by_criterion[ref].append(scenario)

    rows: list[MatrixRow] = []
    for criterion in criteria:
        row = MatrixRow(
            criterion_id=criterion.id,
            criterion_text=criterion.text,
            is_regression=criterion.is_regression,
        )
        covering = by_criterion[criterion.id]
        row.scenario_ids = [scenario.id for scenario in covering]
        if not covering:
            row.status = "no_scenario"
            rows.append(row)
            continue

        # A regression criterion is answered by the pre-existing suite. Its
        # scenarios describe existing behaviour, so matching them against
        # per-test names is neither possible nor needed: the whole suite is
        # the evidence, and one red test in it fails the criterion.
        if criterion.is_regression:
            if regression_cases:
                row.covered_by = "regression"
                row.test_names = [f"{len(regression_cases)} pre-existing tests"]
                row.status = _status_for(regression_cases)
            else:
                row.status = "not_run"
                row.covered_by = "regression"
            rows.append(row)
            continue

        matched = []
        for scenario in covering:
            case = match_scenario(scenario, generated_cases)
            if case is not None and case.name not in [m.name for m in matched]:
                matched.append(case)
        if not matched:
            row.status = "not_automated" if generated_cases else "not_run"
            rows.append(row)
            continue

        row.covered_by = "generated"
        row.test_names = [case.name for case in matched]
        row.status = _status_for(matched)
        rows.append(row)

    return Matrix(rows=rows)
