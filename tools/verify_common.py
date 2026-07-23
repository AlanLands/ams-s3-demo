"""Shared live-verification harness used by tools/verify_s1_live.py,
tools/verify_s2_live.py, and tools/verify_s3_live.py.

Extracted from the original tools/verify_s2_live.py so the PASS/FAIL-table pattern
and cache-snapshot helpers aren't reinvented per scenario. Adds
`run_multi_trial_check` — a single live pass is not evidence of a stable fix: S1's
quality gate flipped pass/fail on identical input across repeated live calls near its
calibration boundary, and a one-shot check would not have caught it.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

StateT = TypeVar("StateT")


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    detail: str
    trials_passed: int | None = None
    trials_total: int | None = None


def run_check(name: str, state: StateT, check: Callable[[StateT], str]) -> CheckResult:
    try:
        detail = check(state)
    except Exception as exc:  # noqa: BLE001 - verifier must continue after each failed check
        return CheckResult(name=name, passed=False, detail=str(exc))
    return CheckResult(name=name, passed=True, detail=detail)


def run_multi_trial_check(
    name: str,
    trial_fn: Callable[[], None],
    trials: int = 5,
    min_pass: int | None = None,
) -> CheckResult:
    """Run `trial_fn` live `trials` times and report how many passed.

    `trial_fn` should raise on failure and return normally on pass. Requires
    LLM_NO_CACHE=1 in the environment — without it, trials 2..N are cache hits of
    trial 1 and prove nothing about live-model stability, which is the exact trap
    a single spot-check fell into for S1's quality gate.
    """
    if os.environ.get("LLM_NO_CACHE") != "1":
        raise RuntimeError(
            f"{name}: run_multi_trial_check requires LLM_NO_CACHE=1 in the "
            "environment — otherwise trials 2..N are cache hits of trial 1 and "
            "prove nothing about live-model stability."
        )
    min_pass = trials if min_pass is None else min_pass

    outcomes: list[tuple[bool, str]] = []
    for _ in range(trials):
        try:
            trial_fn()
            outcomes.append((True, "ok"))
        except Exception as exc:  # noqa: BLE001 - one bad trial must not abort the rest
            outcomes.append((False, str(exc)))

    passed_count = sum(1 for ok, _ in outcomes if ok)
    failures = sorted({detail for ok, detail in outcomes if not ok})
    detail = f"{passed_count}/{trials} passed"
    if failures:
        detail += "; failures: " + "; ".join(failures)[:300]

    return CheckResult(
        name=name,
        passed=passed_count >= min_pass,
        detail=detail,
        trials_passed=passed_count,
        trials_total=trials,
    )


def cache_dir() -> Path:
    return Path(os.environ.get("LLM_CACHE_DIR", ".cache/llm"))


def snapshot_cache() -> dict[Path, float]:
    directory = cache_dir()
    if not directory.exists():
        return {}
    return {path: path.stat().st_mtime for path in directory.glob("*.json")}


def print_summary(results: list[CheckResult]) -> None:
    name_width = max(len("Check"), *(len(result.name) for result in results))
    status_width = len("Status")
    print()
    print(f"{'Check':<{name_width}}  {'Status':<{status_width}}  Detail")
    print(f"{'-' * name_width}  {'-' * status_width}  {'-' * 60}")
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        print(f"{result.name:<{name_width}}  {status:<{status_width}}  {result.detail}")
