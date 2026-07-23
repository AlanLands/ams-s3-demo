"""Autonomous detect -> propose -> apply -> safety-gate -> re-verify -> accept/revert
loop for calibration fixes.

No mid-loop human-approval checkpoint, by explicit request — but two things never
change: nothing here ever runs `git commit`/`git push` (see
tests/test_autofix_no_git_writes.py, a structural guardrail on that), and every run
writes a full audit trail (.cache/autofix_runs/<run_id>/) plus a final diff, so
there's always something concrete to review before anyone commits. The working tree
is guaranteed to be at a fully-verified-or-fully-original state between iterations —
never mid-edit — whether the run converges, gives up, or hits a budget.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from common.telemetry import read_calls  # noqa: E402
from tools.autofix.propose import (  # noqa: E402
    FailureContext,
    PriorAttempt,
    propose_fix,
    validate_proposal,
)
from tools.autofix.splice import SpliceError, read_target, write_target  # noqa: E402
from tools.autofix.targets import REGISTRY  # noqa: E402
from tools.verify_common import CheckResult, print_summary  # noqa: E402

SUBPROCESS_TIMEOUT_S = 120


@dataclass(frozen=True)
class LiveCheckSpec:
    name: str
    trial_fn: Callable[[], None]
    eligible_targets: list[str]


@dataclass(frozen=True)
class ScenarioAdapter:
    scenario: str
    checks: list[LiveCheckSpec]


@dataclass
class AutofixRunResult:
    run_id: str
    scenario: str
    converged: bool
    iterations_used: int
    final_results: list[CheckResult]
    stop_reason: str
    run_dir: Path


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class RunLogger:
    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.events: list[dict] = []

    def log(self, event: str, **fields: object) -> None:
        record = {"ts": _now_iso(), "event": event, **fields}
        self.events.append(record)
        with (self.run_dir / "run.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")

    def write_summary(self, result: AutofixRunResult) -> None:
        lines = [
            f"# Autofix run {result.run_id}",
            "",
            f"Scenario: {result.scenario}",
            f"Converged: {result.converged}",
            f"Iterations used: {result.iterations_used}",
            f"Stop reason: {result.stop_reason}",
            "",
            "## Final check results",
            "",
        ]
        for check in result.final_results:
            status = "PASS" if check.passed else "FAIL"
            lines.append(f"- **{check.name}**: {status} — {check.detail}")
        lines.append("")
        lines.append("## Timeline")
        lines.append("")
        for event in self.events:
            lines.append(f"- `{event['ts']}` **{event['event']}** {_event_summary(event)}")
        (self.run_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def write_diff(self, touched_files: set[Path]) -> None:
        if not touched_files:
            (self.run_dir / "diff.patch").write_text("(no files touched)\n", encoding="utf-8")
            return
        proc = subprocess.run(
            ["git", "diff", "--", *[str(f) for f in sorted(touched_files)]],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT_S,
        )
        (self.run_dir / "diff.patch").write_text(proc.stdout or "(no diff)\n", encoding="utf-8")


def _event_summary(event: dict) -> str:
    skip = {"ts", "event"}
    parts = [f"{k}={v}" for k, v in event.items() if k not in skip]
    return " ".join(parts)[:200]


def _run_trials(trial_fn: Callable[[], None], trials: int) -> tuple[int, list[str]]:
    failures: list[str] = []
    passed = 0
    for _ in range(trials):
        try:
            trial_fn()
            passed += 1
        except Exception as exc:  # noqa: BLE001 - one bad trial must not abort the rest
            failures.append(str(exc))
    return passed, failures


def _ast_parses(file: Path) -> tuple[bool, str]:
    try:
        ast.parse(file.read_text(encoding="utf-8"), filename=str(file))
        return True, "ok"
    except SyntaxError as exc:
        return False, str(exc)


def _run_ruff(file: Path) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            ["ruff", "check", str(file)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return False, f"ruff check timed out after {SUBPROCESS_TIMEOUT_S}s"
    return proc.returncode == 0, (proc.stdout + proc.stderr).strip()[:2000]


def _run_pytest() -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return False, f"pytest timed out after {SUBPROCESS_TIMEOUT_S}s"
    tail = "\n".join((proc.stdout + proc.stderr).splitlines()[-15:])
    return proc.returncode == 0, tail


def _safety_gate(file: Path) -> tuple[bool, str]:
    ok, detail = _ast_parses(file)
    if not ok:
        return False, f"ast.parse failed: {detail}"
    ok, detail = _run_ruff(file)
    if not ok:
        return False, f"ruff failed: {detail}"
    ok, detail = _run_pytest()
    if not ok:
        return False, f"pytest failed:\n{detail}"
    return True, "ast + ruff + pytest all clean"


def _count_new_live_calls(start_count: int) -> int:
    calls = read_calls()
    return sum(1 for call in calls[start_count:] if not call.get("cached"))


def run_autofix_loop(
    adapter: ScenarioAdapter,
    *,
    max_iterations: int = 4,
    trials: int = 5,
    max_live_calls: int = 150,
    max_wall_clock_s: int = 1800,
    dry_run: bool = False,
) -> AutofixRunResult:
    # Every check here is a multi-trial live check — some scenarios (S2) use a
    # fixed per-cluster cache_key by design, so without this, trials 2..N would
    # silently be cache hits of trial 1 and the whole loop would prove nothing.
    # Safe for the pytest subprocess in _safety_gate too: mocked tests never call
    # complete() for real, so this has no effect there.
    os.environ["LLM_NO_CACHE"] = "1"

    run_id = f"{adapter.scenario}-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"
    run_dir = REPO_ROOT / ".cache" / "autofix_runs" / run_id
    logger = RunLogger(run_dir)
    logger.log(
        "run_start", scenario=adapter.scenario, dry_run=dry_run, max_iterations=max_iterations
    )

    start_call_count = len(read_calls())
    start_time = time.monotonic()

    # last_known_good_value: only ever the original value, or a value that has
    # itself passed the full safety gate + re-verify — never a rejected attempt.
    last_known_good: dict[str, str] = {}
    touched_files: set[Path] = set()
    prior_attempts: dict[str, list[PriorAttempt]] = {}

    def elapsed_s() -> float:
        return time.monotonic() - start_time

    def budget_exceeded() -> str | None:
        if elapsed_s() > max_wall_clock_s:
            return f"wall-clock budget exceeded ({elapsed_s():.0f}s > {max_wall_clock_s}s)"
        used = _count_new_live_calls(start_call_count)
        if used > max_live_calls:
            return f"live-call budget exceeded ({used} > {max_live_calls})"
        return None

    def detect(trial_count: int) -> list[CheckResult]:
        results = []
        for check in adapter.checks:
            passed, failures = _run_trials(check.trial_fn, trial_count)
            detail = f"{passed}/{trial_count} passed"
            if failures:
                detail += "; e.g. " + "; ".join(sorted(set(failures))[:3])[:300]
            results.append(
                CheckResult(
                    name=check.name,
                    passed=passed == trial_count,
                    detail=detail,
                    trials_passed=passed,
                    trials_total=trial_count,
                )
            )
            logger.log(
                "detect",
                check=check.name,
                passed=passed,
                total=trial_count,
                failures=failures[:5],
            )
        return results

    results = detect(trials)
    iteration = 0
    stop_reason = "converged" if all(r.passed for r in results) else ""

    while not stop_reason:
        if iteration >= max_iterations:
            stop_reason = "gave_up_after_max_iterations"
            break

        reason = budget_exceeded()
        if reason:
            stop_reason = f"budget_exhausted: {reason}"
            logger.log("budget_exhausted", detail=reason)
            break

        iteration += 1
        failing = [
            (check, result)
            for check, result in zip(adapter.checks, results, strict=True)
            if not result.passed
        ]

        made_progress = False
        for check, result in failing:
            target_id = check.eligible_targets[0] if check.eligible_targets else None
            if not target_id or target_id not in REGISTRY:
                logger.log("no_eligible_target", check=check.name)
                continue

            target = REGISTRY[target_id]
            try:
                current_value = last_known_good.get(target_id) or read_target(target)
            except SpliceError as exc:
                logger.log("target_unreadable", check=check.name, target=target_id, error=str(exc))
                continue
            last_known_good.setdefault(target_id, current_value)

            ctx = FailureContext(
                scenario=adapter.scenario,
                check_name=check.name,
                detail=result.detail,
                target=target,
                current_value=current_value,
                worst_trial_examples=result.detail.split("; e.g. ")[-1].split("; ")
                if "; e.g. " in result.detail
                else [],
                prior_attempts=prior_attempts.get(target_id, []),
            )

            logger.log("propose_start", check=check.name, target=target_id, iteration=iteration)
            if dry_run:
                logger.log("dry_run_skip_propose", check=check.name, target=target_id)
                continue

            try:
                proposal = propose_fix(ctx, run_id=run_id, iteration=iteration)
            except Exception as exc:  # noqa: BLE001 - a bad meta-call must not crash the run
                logger.log("propose_failed", check=check.name, target=target_id, error=str(exc))
                continue

            error = validate_proposal(proposal, target, current_value)
            if error:
                logger.log("proposal_rejected", check=check.name, target=target_id, error=error)
                prior_attempts.setdefault(target_id, []).append(
                    PriorAttempt(value=proposal.new_value, outcome=f"rejected: {error}")
                )
                continue

            try:
                write_target(target, proposal.new_value)
            except SpliceError as exc:
                logger.log("apply_failed", check=check.name, target=target_id, error=str(exc))
                prior_attempts.setdefault(target_id, []).append(
                    PriorAttempt(value=proposal.new_value, outcome=f"splice failed: {exc}")
                )
                continue
            touched_files.add(target.file)
            logger.log(
                "applied",
                check=check.name,
                target=target_id,
                rationale=proposal.rationale,
                new_value_preview=proposal.new_value[:200],
            )

            gate_ok, gate_detail = _safety_gate(target.file)
            logger.log("safety_gate", target=target_id, ok=gate_ok, detail=gate_detail[:500])
            if not gate_ok:
                write_target(target, last_known_good[target_id])
                logger.log("reverted", target=target_id, reason="safety_gate")
                prior_attempts.setdefault(target_id, []).append(
                    PriorAttempt(
                        value=proposal.new_value,
                        outcome=f"safety gate failed: {gate_detail[:200]}",
                    )
                )
                continue

            # Re-verify at full rigor, every check this target is eligible for —
            # not just the one that triggered the fix.
            affected = [c for c in adapter.checks if target_id in c.eligible_targets]
            reverify_pass = True
            reverify_details = []
            for affected_check in affected:
                passed, failures = _run_trials(affected_check.trial_fn, trials)
                reverify_details.append(f"{affected_check.name}: {passed}/{trials}")
                if passed != trials:
                    reverify_pass = False
            logger.log(
                "reverify",
                target=target_id,
                ok=reverify_pass,
                detail="; ".join(reverify_details),
            )

            if reverify_pass:
                last_known_good[target_id] = proposal.new_value
                made_progress = True
                logger.log("accepted", target=target_id)
                prior_attempts.setdefault(target_id, []).append(
                    PriorAttempt(value=proposal.new_value, outcome="accepted")
                )
            else:
                write_target(target, last_known_good[target_id])
                logger.log("reverted", target=target_id, reason="reverify_failed")
                prior_attempts.setdefault(target_id, []).append(
                    PriorAttempt(
                        value=proposal.new_value,
                        outcome=f"reverify failed: {'; '.join(reverify_details)}",
                    )
                )

        results = detect(trials)
        if dry_run:
            stop_reason = "dry_run_complete"
        elif all(r.passed for r in results):
            stop_reason = "converged"
        elif not made_progress:
            stop_reason = "no_eligible_fix_or_no_progress"
        # else: made progress but not fully converged yet — loop continues.

    converged = all(r.passed for r in results)
    result = AutofixRunResult(
        run_id=run_id,
        scenario=adapter.scenario,
        converged=converged,
        iterations_used=iteration,
        final_results=results,
        stop_reason=stop_reason,
        run_dir=run_dir,
    )
    logger.log("run_end", converged=converged, stop_reason=result.stop_reason, iterations=iteration)
    logger.write_summary(result)
    logger.write_diff(touched_files)
    return result


def _print_result(result: AutofixRunResult) -> None:
    print_summary(result.final_results)
    print()
    print(f"run_id: {result.run_id}")
    print(f"converged: {result.converged}  stop_reason: {result.stop_reason}  "
          f"iterations: {result.iterations_used}")
    print(f"artifacts: {result.run_dir}/run.jsonl, summary.md, diff.patch")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Autonomous calibration fix loop")
    parser.add_argument("--scenario", default="s3", choices=["s3"])
    parser.add_argument("--max-iterations", type=int, default=4)
    parser.add_argument("--trials", type=int, default=5)
    parser.add_argument("--max-live-calls", type=int, default=150)
    parser.add_argument("--max-wall-clock-s", type=int, default=1800)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    from tools.autofix.adapters.s3 import build_adapter

    adapter = build_adapter()
    result = run_autofix_loop(
        adapter,
        max_iterations=args.max_iterations,
        trials=args.trials,
        max_live_calls=args.max_live_calls,
        max_wall_clock_s=args.max_wall_clock_s,
        dry_run=args.dry_run,
    )
    _print_result(result)
    return 0 if result.converged else 1


if __name__ == "__main__":
    raise SystemExit(main())
