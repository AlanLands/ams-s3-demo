"""Verifies s3_enhancement/testrun.py — JUnit XML parsing, test-name
humanization, and the mutation beat's always-revert guarantee."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from s3_enhancement import testrun
from s3_enhancement.targets import Mutation
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
        targets.SPRINGDEMO_CLAIMS_DEDUCTIBLE,
    ):
        assert target.mutations, f"{target.target_id} has no seeded mutation"
