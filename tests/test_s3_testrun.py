"""Verifies s3_enhancement/testrun.py — JUnit XML parsing, test-name
humanization, and the mutation beat's always-revert guarantee."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from s3_enhancement import testrun
from s3_enhancement.targets import Mutation, Target
from s3_enhancement.testrun import (
    MutationError,
    SuiteRun,
    _parse_junit_files,
    humanize_test_name,
    run_mutation,
)

JUNIT_XML = """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="pytest" errors="0" failures="1" skipped="1" tests="3" time="0.05">
    <testcase classname="tests.test_x" name="test_default_tier_is_standard" time="0.011"/>
    <testcase classname="tests.test_x" name="test_same_tier_raises_value_error" time="0.002">
      <failure message="ValueError not raised">traceback here</failure>
    </testcase>
    <testcase classname="tests.test_x" name="test_skipped_one" time="0">
      <skipped message="not relevant"/>
    </testcase>
  </testsuite>
</testsuites>
"""


def test_humanize_snake_case_pytest_name():
    assert (
        humanize_test_name("test_unknown_tier_raises_value_error")
        == "Unknown tier raises value error"
    )


def test_humanize_camel_case_junit_name():
    assert (
        humanize_test_name("claimAtExactlyDeductibleIsRejected")
        == "Claim at exactly deductible is rejected"
    )


def test_humanize_keeps_parametrize_suffix():
    assert humanize_test_name("test_upgrade[Premium]") == "Upgrade [Premium]"


def test_parse_junit_files_statuses_and_messages(tmp_path):
    xml_path = tmp_path / "junit.xml"
    xml_path.write_text(JUNIT_XML, encoding="utf-8")

    cases = _parse_junit_files([xml_path])

    assert [case.status for case in cases] == ["passed", "failed", "skipped"]
    assert cases[0].message is None
    assert cases[1].message == "ValueError not raised"
    assert cases[1].description == "Same tier raises value error"
    assert cases[0].time_s == pytest.approx(0.011)


def test_parse_junit_files_tolerates_missing_file(tmp_path):
    assert _parse_junit_files([tmp_path / "never-written.xml"]) == []


def test_suite_run_summary_counts():
    run = SuiteRun(
        output="",
        returncode=1,
        cases=_parse_junit_files_from_text(JUNIT_XML),
        duration_s=0.1,
    )
    assert run.summary() == {"total": 3, "passed": 1, "failed": 1, "errors": 0, "skipped": 1}
    assert run.passed is False


def _parse_junit_files_from_text(xml_text: str):
    import tempfile

    with tempfile.TemporaryDirectory() as tmp_dir:
        xml_path = Path(tmp_dir) / "junit.xml"
        xml_path.write_text(xml_text, encoding="utf-8")
        return _parse_junit_files([xml_path])


def _mutation_target(tmp_path, monkeypatch) -> SimpleNamespace:
    """A fake target rooted in tmp_path, with one seeded mutation and an
    existing generated test file."""
    monkeypatch.setattr(testrun, "REPO_ROOT", tmp_path)
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "logic.py").write_text(
        "def guard(a, b):\n    if a <= b:\n        raise ValueError('nope')\n",
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_generated.py").write_text("def test_ok():\n    pass\n")
    return SimpleNamespace(
        mutations=(
            Mutation(
                rel_path="app/logic.py",
                old_snippet="if a <= b:",
                new_snippet="if a < b:",
                description="Weakened the guard",
            ),
        ),
        testgen_allowlist=("tests/test_generated.py",),
        test_command=(),
        test_cwd=None,
    )


def test_run_mutation_reverts_after_run(tmp_path, monkeypatch):
    target = _mutation_target(tmp_path, monkeypatch)
    original = (tmp_path / "app" / "logic.py").read_text(encoding="utf-8")
    seen_during_run: dict[str, str] = {}

    def fake_run_suite(_target):
        seen_during_run["content"] = (tmp_path / "app" / "logic.py").read_text(encoding="utf-8")
        return SuiteRun(output="1 failed", returncode=1, cases=[], duration_s=0.1)

    with patch.object(testrun, "run_suite", side_effect=fake_run_suite):
        result = run_mutation(target)

    assert "if a < b:" in seen_during_run["content"]
    assert (tmp_path / "app" / "logic.py").read_text(encoding="utf-8") == original
    assert result.tests_caught_bug is True
    assert "-    if a <= b:" in result.mutation_diff
    assert "+    if a < b:" in result.mutation_diff


def test_run_mutation_reverts_even_when_suite_crashes(tmp_path, monkeypatch):
    target = _mutation_target(tmp_path, monkeypatch)
    original = (tmp_path / "app" / "logic.py").read_text(encoding="utf-8")

    with (
        patch.object(testrun, "run_suite", side_effect=RuntimeError("runner exploded")),
        pytest.raises(RuntimeError),
    ):
        run_mutation(target)

    assert (tmp_path / "app" / "logic.py").read_text(encoding="utf-8") == original


def test_run_mutation_requires_generated_tests(tmp_path, monkeypatch):
    target = _mutation_target(tmp_path, monkeypatch)
    (tmp_path / "tests" / "test_generated.py").unlink()

    with pytest.raises(MutationError, match="no generated test file"):
        run_mutation(target)


def test_run_mutation_rejects_drifted_content(tmp_path, monkeypatch):
    target = _mutation_target(tmp_path, monkeypatch)
    (tmp_path / "app" / "logic.py").write_text("completely different\n", encoding="utf-8")

    with pytest.raises(MutationError, match="drifted"):
        run_mutation(target)


def test_demo_targets_all_declare_a_mutation():
    """Every demo target should be able to run the "prove the tests" beat.
    (Checked by name, not via all_targets() — other test modules register
    throwaway targets into the shared registry.)"""
    from s3_enhancement import targets

    for target in (
        targets.MOCKAPP_COVERAGE_UPGRADE,
        targets.MOCKAPP_ENDORSEMENT_FIELD_ADD,
        targets.CLAIMSPORTAL_CLAIMS_DEDUCTIBLE,
    ):
        assert target.mutations, f"{target.target_id} has no seeded mutation"


def test_demo_targets_all_declare_a_regression_suite():
    """The counterpart to the mutation check: every demo target must be able
    to answer "did this break anything that already worked?"."""
    from s3_enhancement import targets

    for target in (
        targets.MOCKAPP_COVERAGE_UPGRADE,
        targets.MOCKAPP_ENDORSEMENT_FIELD_ADD,
        targets.CLAIMSPORTAL_CLAIMS_DEDUCTIBLE,
    ):
        assert target.has_regression_suite, f"{target.target_id} has no regression suite"


def test_regression_suite_is_never_writable_by_the_pipeline():
    """The whole claim rests on the AI being unable to touch these files. If a
    regression path ever appeared in a testgen or codegen allowlist, the suite
    would be marking its own homework."""
    from s3_enhancement import targets

    for target in targets.all_targets():
        writable = set(target.testgen_allowlist) | set(target.codegen_allowlist)
        for path in target.regression_paths:
            assert path not in writable, f"{target.target_id} can overwrite {path}"


def _regression_target(**overrides) -> Target:
    """A minimal, unregistered Target — enough for run_regression's dispatch."""
    return Target(
        target_id="fake-regression-target",
        source_kind="local",
        display_name="fake",
        **overrides,
    )


def test_run_regression_rejects_a_target_without_a_suite():
    with pytest.raises(testrun.NoRegressionSuiteError, match="no checked-in regression suite"):
        testrun.run_regression(_regression_target())


def test_run_regression_uses_pytest_paths_when_no_command_declared():
    target = _regression_target(regression_paths=("tests/test_regression_example.py",))
    captured: dict = {}

    def fake_pytest(paths):
        captured["paths"] = paths
        return SuiteRun(output="", returncode=0, cases=[], duration_s=0.0)

    with patch.object(testrun, "_run_pytest", side_effect=fake_pytest):
        testrun.run_regression(target)

    assert captured["paths"] == ["tests/test_regression_example.py"]


def test_run_regression_prefers_a_declared_command(tmp_path):
    target = _regression_target(
        regression_paths=("tests/ignored.py",),
        regression_command=("mvn", "-q", "test"),
        regression_cwd=tmp_path,
    )
    captured: dict = {}

    def fake_external(command, cwd):
        captured["command"] = command
        captured["cwd"] = cwd
        return SuiteRun(output="", returncode=0, cases=[], duration_s=0.0)

    with patch.object(testrun, "_run_external", side_effect=fake_external):
        testrun.run_regression(target)

    assert captured["command"] == ["mvn", "-q", "test"]
    assert captured["cwd"] == tmp_path
