"""Structured test execution for the S3 "Generate tests + run" beat.

Runs a target's generated test suite with the target's own runner (pytest by
default, the Target's declared Maven invocation for a Java target) and parses
the run into per-test-case results via JUnit XML — pytest writes it with
`--junitxml`, Maven's Surefire writes the same schema to
`target/surefire-reports/` — so the console can render a per-test checklist
instead of a raw runner dump. The raw output is always kept alongside; a run
whose XML never appeared (runner crashed before writing it) still returns,
just with an empty case list and the real returncode.

Also home to the "prove the tests catch bugs" beat: `run_mutation()` applies a
target's seeded, deterministic bug (see `targets.Mutation`), re-runs the
generated suite, and always restores the original file content — the working
tree is byte-identical afterwards no matter how the run ends.

`run_regression()` is the counterpart to `run_suite()`: same runners, same
parsing, but pointed at the target app's checked-in suite instead of the
generated one. Keeping them as two calls rather than one merged run is the
whole point — "12 new tests pass" and "20 pre-existing tests still pass" are
different claims, and a CR that breaks the second while satisfying the first
is exactly the failure this beat exists to catch.
"""

from __future__ import annotations

import difflib
import re
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from s3_enhancement.targets import Mutation, Target

REPO_ROOT = Path(__file__).resolve().parents[1]


class TestRunnerNotFoundError(Exception):
    """The target's declared test runner binary is not on PATH."""


class NoRegressionSuiteError(Exception):
    """The target has no checked-in regression suite registered."""


class MutationError(Exception):
    """The mutation beat cannot run — no seeded mutation matches the current
    generated code, or the generated test file doesn't exist yet."""


@dataclass
class TestCase:
    name: str
    classname: str
    description: str
    status: str  # "passed" | "failed" | "error" | "skipped"
    time_s: float
    message: str | None


@dataclass
class SuiteRun:
    output: str
    returncode: int
    cases: list[TestCase]
    duration_s: float

    @property
    def passed(self) -> bool:
        return self.returncode == 0

    def summary(self) -> dict[str, int]:
        counts = {"total": len(self.cases), "passed": 0, "failed": 0, "errors": 0, "skipped": 0}
        for case in self.cases:
            if case.status == "passed":
                counts["passed"] += 1
            elif case.status == "failed":
                counts["failed"] += 1
            elif case.status == "error":
                counts["errors"] += 1
            elif case.status == "skipped":
                counts["skipped"] += 1
        return counts


@dataclass
class MutationRun:
    description: str
    rel_path: str
    mutation_diff: str
    run: SuiteRun
    tests_caught_bug: bool


def humanize_test_name(name: str) -> str:
    """Plain-English label from a test identifier, for the results table.

    `test_unknown_tier_raises_value_error` -> "Unknown tier raises value error";
    Java's `claimAtExactlyDeductibleIsRejected` -> "Claim at exactly deductible
    is rejected". Parametrized pytest ids keep their bracket suffix verbatim.
    """
    base, _, params = name.partition("[")
    base = re.sub(r"^test[_ ]?", "", base, flags=re.IGNORECASE) or base
    words = base.replace("_", " ").strip()
    words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", words).lower()
    label = words[:1].upper() + words[1:] if words else name
    return f"{label} [{params}" if params else label


def _parse_junit_files(xml_paths: list[Path]) -> list[TestCase]:
    cases: list[TestCase] = []
    for xml_path in xml_paths:
        try:
            root = ET.parse(xml_path).getroot()
        except (ET.ParseError, OSError):
            continue
        for case_el in root.iter("testcase"):
            name = case_el.get("name", "")
            status = "passed"
            message: str | None = None
            for child in case_el:
                if child.tag in ("failure", "error", "skipped"):
                    status = {"failure": "failed", "error": "error", "skipped": "skipped"}[
                        child.tag
                    ]
                    message = child.get("message") or (child.text or "").strip() or None
                    break
            try:
                time_s = float(case_el.get("time", "0") or 0)
            except ValueError:
                time_s = 0.0
            cases.append(
                TestCase(
                    name=name,
                    classname=case_el.get("classname", ""),
                    description=humanize_test_name(name),
                    status=status,
                    time_s=time_s,
                    message=message,
                )
            )
    return cases


def _run(argv: list[str], cwd: Path | None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            argv, check=False, capture_output=True, text=True, cwd=cwd
        )
    except FileNotFoundError as exc:
        raise TestRunnerNotFoundError(
            f"Test runner {argv[0]!r} not found — is it installed on PATH?"
        ) from exc


def _run_external(command: list[str], cwd: Path | None) -> SuiteRun:
    """Run a target-declared command (Maven today) and parse Surefire's XML."""
    start = time.monotonic()
    # Surefire writes one TEST-*.xml per class into target/surefire-reports;
    # clear stale reports first so a parse can never pick up a previous run.
    reports_dir = (cwd or REPO_ROOT) / "target" / "surefire-reports"
    if reports_dir.exists():
        for stale in reports_dir.glob("TEST-*.xml"):
            stale.unlink(missing_ok=True)
    process = _run(command, cwd)
    xml_paths = sorted(reports_dir.glob("TEST-*.xml")) if reports_dir.exists() else []
    return SuiteRun(
        output=process.stdout + process.stderr,
        returncode=process.returncode,
        cases=_parse_junit_files(xml_paths),
        duration_s=time.monotonic() - start,
    )


def _run_pytest(test_paths: list[str]) -> SuiteRun:
    start = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="s3-junit-") as tmp_dir:
        xml_path = Path(tmp_dir) / "junit.xml"
        process = _run(
            [
                sys.executable,
                "-m",
                "pytest",
                *test_paths,
                "-v",
                f"--junitxml={xml_path}",
                "-o",
                "junit_family=xunit2",
            ],
            REPO_ROOT,
        )
        cases = _parse_junit_files([xml_path])
    return SuiteRun(
        output=process.stdout + process.stderr,
        returncode=process.returncode,
        cases=cases,
        duration_s=time.monotonic() - start,
    )


def run_suite(target: Target) -> SuiteRun:
    """Run the target's generated tests and parse per-case results."""
    if target.test_command:
        return _run_external(list(target.test_command), target.test_cwd)
    test_path = target.testgen_allowlist[0] if target.testgen_allowlist else ""
    return _run_pytest([test_path])


def run_regression(target: Target) -> SuiteRun:
    """Run the target app's checked-in, pre-existing regression suite.

    Deliberately independent of whether the generated suite exists or has been
    run: the point of the beat is that these tests predate the change, so they
    are runnable before a single line of it has been generated. That also makes
    them usable as a *baseline* — run them before Apply and again after, and
    the pair is the evidence that the CR broke nothing.
    """
    if not target.has_regression_suite:
        raise NoRegressionSuiteError(
            f"Target {target.target_id!r} has no checked-in regression suite registered."
        )
    if target.regression_command:
        return _run_external(list(target.regression_command), target.regression_cwd)
    return _run_pytest(list(target.regression_paths))


def generated_test_file_exists(target: Target) -> bool:
    return bool(
        target.testgen_allowlist and (REPO_ROOT / target.testgen_allowlist[0]).exists()
    )


def _select_mutation(target: Target) -> tuple[Mutation, Path, str]:
    if not target.mutations:
        raise MutationError("This target has no seeded mutation registered.")
    for mutation in target.mutations:
        path = REPO_ROOT / mutation.rel_path
        if not path.exists():
            continue
        content = path.read_text(encoding="utf-8")
        if mutation.old_snippet in content:
            return mutation, path, content
    raise MutationError(
        "No seeded mutation matches the current generated code — the generated "
        "content has drifted from the recorded run. Re-run the generate/apply "
        "steps, or re-record the demo caches."
    )


def run_mutation(target: Target) -> MutationRun:
    """Inject the target's seeded bug, re-run the suite, always revert."""
    if not generated_test_file_exists(target):
        raise MutationError(
            "Generate and run the tests first — there is no generated test file "
            "to prove yet."
        )
    mutation, path, original = _select_mutation(target)
    mutated = original.replace(mutation.old_snippet, mutation.new_snippet, 1)
    mutation_diff = "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            mutated.splitlines(keepends=True),
            fromfile=f"a/{mutation.rel_path}",
            tofile=f"b/{mutation.rel_path}",
        )
    )
    path.write_text(mutated, encoding="utf-8")
    try:
        run = run_suite(target)
    finally:
        path.write_text(original, encoding="utf-8")
    return MutationRun(
        description=mutation.description,
        rel_path=mutation.rel_path,
        mutation_diff=mutation_diff,
        run=run,
        tests_caught_bug=run.returncode != 0,
    )
