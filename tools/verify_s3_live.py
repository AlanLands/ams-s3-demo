"""Verify S3's live-primary codegen architecture end to end.

Two layers of checks:

1. **Architecture checks** (no live model needed, run with `--skip-live` too):
   the replay safety net works fully offline, a mid-stream provider failure
   falls back to replay invisibly, one recording replays correctly for any
   audience-chosen tier name, and `demo/reset_s3.sh` restores the pre-CR
   baseline in <10s.
2. **Live checks**: the narrative drafts (effort estimate / impact analysis /
   release notes) run 5x against the real provider and must be structurally
   sound every time — not graded for *quality*, which would need another LLM
   and reintroduce the non-determinism this tooling exists to catch.

`--gate N` runs the rehearsal gate: N full live codegen+testgen+pytest cycles
from baseline. A cycle passes only if the LIVE path succeeded (no silent
replay fallback) and the generated tests run green. The demo-day rule from the
S3 build plan: codegen must pass live >= 9/10 consecutive runs before demo
day, otherwise present in LLM_MODE=replay without hesitation.

All tree-mutating checks restore the committed post-CR state before exiting.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import common.llm as llm_mod  # noqa: E402
from common.llm import LLMError  # noqa: E402
from s3_enhancement import relevance  # noqa: E402
from s3_enhancement.analyze import draft_effort_estimate, draft_impact_analysis  # noqa: E402
from s3_enhancement.codegen import generate_change  # noqa: E402
from s3_enhancement.cr import render_cr  # noqa: E402
from s3_enhancement.docgen import draft_release_notes  # noqa: E402
from s3_enhancement.harness import HarnessError, run_harness  # noqa: E402
from s3_enhancement.testgen import generate_tests  # noqa: E402
from tools.verify_common import (  # noqa: E402
    CheckResult,
    print_summary,
    run_check,
    run_multi_trial_check,
    snapshot_cache,
)

_BASELINE_FILES = ("repos/policycore/app.py", "repos/policycore/core/models.py", "repos/policycore/core/db.py")
_GENERATED_FILES = ("repos/policycore/core/tiers.py", "tests/test_s3_tier_upgrade.py")

_REFUSAL_MARKERS = ("as an ai", "i cannot", "i'm sorry, but", "i am unable to")
_MIN_LENGTH = 40


@dataclass
class VerificationState:
    cr_text: str = render_cr("Elite")


# --- helpers for the architecture checks -------------------------------------


def _git_show(ref_path: str, target: Path) -> None:
    content = subprocess.run(
        ["git", "show", ref_path],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    target.write_text(content, encoding="utf-8")


def _restore_baseline() -> None:
    """Put mockapp back in the pre-CR state (same file set as demo/reset_s3.sh),
    without wiping the shared LLM cache the way the reset script does."""
    for rel in _BASELINE_FILES:
        _git_show(f"s3-baseline:{rel}", REPO_ROOT / rel)
    for rel in _GENERATED_FILES:
        (REPO_ROOT / rel).unlink(missing_ok=True)
    _reseed()


def _restore_committed_state() -> None:
    """Restore the committed working state after tree-mutating checks.

    Only `_BASELINE_FILES` are committed source, so only they can come back
    from HEAD. `_GENERATED_FILES` are pipeline output that has never been
    committed — `git show HEAD:...` on those fails, and since this runs in a
    `finally`, that failure used to mask every check result behind a
    CalledProcessError. They get deleted instead, which is what "restore the
    committed state" means for a file the commit doesn't contain.
    """
    for rel in _BASELINE_FILES:
        _git_show(f"HEAD:{rel}", REPO_ROOT / rel)
    for rel in _GENERATED_FILES:
        (REPO_ROOT / rel).unlink(missing_ok=True)
    _reseed()


def _reseed() -> None:
    subprocess.run(
        [sys.executable, "-m", "repos.policycore.core.seed"],
        cwd=REPO_ROOT,
        env=_child_env(),
        capture_output=True,
        check=True,
    )


def _child_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{REPO_ROOT}{os.pathsep}{env.get('PYTHONPATH', '')}"
    return env


def _run_generated_tests() -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_s3_tier_upgrade.py", "-q"],
        cwd=REPO_ROOT,
        env=_child_env(),
        capture_output=True,
        text=True,
    )


def _hash_tree(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            digest.update(str(path.relative_to(root)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


@contextmanager
def _patched_streamers(replacement) -> Iterator[None]:
    """Swap every provider streamer (and blocking caller) for `replacement` so a
    check can prove replay never touches the network / simulate a provider drop."""
    saved_streamers = dict(llm_mod._PROVIDER_STREAMERS)
    saved_callers = dict(llm_mod._PROVIDER_CALLERS)
    for key in llm_mod._PROVIDER_STREAMERS:
        llm_mod._PROVIDER_STREAMERS[key] = replacement
    for key in llm_mod._PROVIDER_CALLERS:
        llm_mod._PROVIDER_CALLERS[key] = replacement
    try:
        yield
    finally:
        llm_mod._PROVIDER_STREAMERS.update(saved_streamers)
        llm_mod._PROVIDER_CALLERS.update(saved_callers)


@contextmanager
def _env(name: str, value: str) -> Iterator[None]:
    old = os.environ.get(name)
    os.environ[name] = value
    try:
        yield
    finally:
        if old is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = old


def _run_full_generation(tier_name: str) -> tuple[bool, bool]:
    """Run codegen + testgen for `tier_name` against the current LLM_MODE.
    Returns (codegen_used_replay, testgen_used_replay); raises on hard failure."""
    cr_text = render_cr(tier_name)
    change = generate_change(tier_name, cr_text)
    tests = generate_tests(tier_name, cr_text)
    return change.used_replay, tests.used_replay


# --- architecture checks ------------------------------------------------------


def check_replay_fully_offline(state: VerificationState) -> str:
    """The demo's safety net: with every provider path booby-trapped, a replay
    run must still produce the working feature and green tests."""

    def _network_forbidden(*args, **kwargs):
        raise AssertionError("replay mode touched a provider — it must be fully offline")

    _restore_baseline()
    with _env("LLM_MODE", "replay"), _patched_streamers(_network_forbidden):
        used_replay = _run_full_generation("Elite")
    if used_replay != (True, True):
        raise AssertionError(f"expected both steps to replay, got {used_replay}")
    result = _run_generated_tests()
    if result.returncode != 0:
        raise AssertionError(f"generated tests failed after offline replay:\n{result.stdout}")
    return "baseline -> replay codegen+testgen -> pytest green, zero network"


def check_network_kill_mid_codegen(state: VerificationState) -> str:
    """Acceptance check #3: provider dies mid-stream in live mode -> the step
    auto-completes via replay, no stack trace, tests still green."""

    def _drops_mid_stream(prompt, system, json_mode, *, usage_out=None):
        yield '{"files": ['
        raise ConnectionError("simulated network drop mid-stream")

    _restore_baseline()
    with _env("LLM_MODE", "live"), _patched_streamers(_drops_mid_stream):
        used_replay = _run_full_generation("Elite")
    if not used_replay[0]:
        raise AssertionError("codegen claimed a live pass while the provider was dropping")
    result = _run_generated_tests()
    if result.returncode != 0:
        raise AssertionError(f"generated tests failed after fallback:\n{result.stdout}")
    return "mid-stream drop -> silent replay fallback -> pytest green"


def check_two_tier_names_replay(state: VerificationState) -> str:
    """Acceptance check #6: one recording must replay correctly for any
    audience-chosen tier name — the crux of the {{TIER_NAME}} design."""
    details = []
    for tier in ("Aurora", "Titanium"):
        _restore_baseline()
        with _env("LLM_MODE", "replay"):
            _run_full_generation(tier)
        tiers_src = (REPO_ROOT / "repos/policycore/core/tiers.py").read_text(encoding="utf-8")
        if tier not in tiers_src:
            raise AssertionError(f"tier {tier!r} missing from replayed tiers.py")
        if "{{TIER_NAME}}" in tiers_src:
            raise AssertionError("placeholder token leaked into replayed tiers.py")
        result = _run_generated_tests()
        if result.returncode != 0:
            raise AssertionError(f"tests failed for tier {tier!r}:\n{result.stdout}")
        details.append(tier)
    return f"replayed {' and '.join(details)} from one recording, tests green both times"


def check_reset_speed(state: VerificationState) -> str:
    """Acceptance check #4: reset_s3.sh restores the pre-CR app in <10s."""
    t0 = time.monotonic()
    result = subprocess.run(
        ["bash", "demo/reset_s3.sh"], cwd=REPO_ROOT, capture_output=True, text=True
    )
    elapsed = time.monotonic() - t0
    if result.returncode != 0:
        raise AssertionError(f"reset_s3.sh failed:\n{result.stderr}")
    if elapsed >= 10:
        raise AssertionError(f"reset took {elapsed:.1f}s, must be <10s")
    if (REPO_ROOT / "repos/policycore/core/tiers.py").exists():
        raise AssertionError("coverage.py still present after reset")
    app_text = (REPO_ROOT / "repos/policycore/app.py").read_text(encoding="utf-8")
    if "Upgrade Coverage" in app_text:
        raise AssertionError("upgrade UI still present in repos/policycore/app.py after reset")
    return f"reset in {elapsed:.1f}s, baseline restored"


def check_core_recall_never_drops(state: VerificationState) -> str:
    all_files = relevance.discover_mockapp_files()
    for tier in ("Elite", "Titanium", "Aurora"):
        selection = relevance.select_relevant_files(render_cr(tier), all_files)
        if not set(relevance.CORE_FILES) <= set(selection.selected):
            missing = set(relevance.CORE_FILES) - set(selection.selected)
            raise AssertionError(f"{tier}: selected scope dropped core files {sorted(missing)}")
    return "core S3 files retained across Elite, Titanium, and Aurora CR variants"


def check_decoys_never_selected(state: VerificationState) -> str:
    selection = relevance.select_relevant_files(state.cr_text, relevance.discover_mockapp_files())
    selected_decoys = [
        path
        for path in (*selection.selected, *selection.extra_files)
        if path.startswith("repos/policycore/systems/")
    ]
    if selected_decoys:
        raise AssertionError(f"decoy files selected for canonical CR: {selected_decoys}")
    return "canonical CR selected no repos/policycore/systems decoys"


def check_design_doc_gate_screens_all_legacy_subsystems(state: VerificationState) -> str:
    """The demo claims the AI reads subsystem design docs first, before ever
    opening a Java file — this proves that gate actually screens out every
    legacy subsystem for the canonical CR across all three tier-name variants,
    not just that individual files end up unselected downstream."""
    docs = relevance.discover_subsystem_design_docs()
    if not docs:
        raise AssertionError("no repos/policycore/systems/*/DESIGN.md docs found")
    for tier in ("Elite", "Titanium", "Aurora"):
        screen = relevance.screen_subsystems(render_cr(tier), docs)
        if screen.in_scope:
            raise AssertionError(f"{tier}: design-doc gate let subsystems through: "
                                  f"{screen.in_scope}")
        if set(screen.screened_out) != set(docs):
            raise AssertionError(f"{tier}: gate did not screen every discovered subsystem")
    return f"design-doc gate screened out all {len(docs)} legacy subsystems, all tier variants"


# --- rehearsal gate ------------------------------------------------------------


def run_rehearsal_gate(cycles: int) -> int:
    """N full live cycles from baseline. A cycle passes only if BOTH steps ran
    genuinely live (no replay fallback) and the generated tests are green."""
    passes = 0
    print(f"Rehearsal gate: {cycles} live codegen+testgen cycles (tier 'Elite')\n")
    for i in range(1, cycles + 1):
        t0 = time.monotonic()
        _restore_baseline()
        try:
            with _env("LLM_MODE", "live"):
                used_replay = _run_full_generation("Elite")
            tests_green = _run_generated_tests().returncode == 0
            live = not any(used_replay)
            ok = live and tests_green
        except Exception as exc:  # noqa: BLE001 — a hard failure is a failed cycle
            used_replay, tests_green, live, ok = ("-", "-"), False, False, False
            print(f"  cycle {i}: hard failure: {exc}")
        passes += ok
        print(
            f"  cycle {i}/{cycles}: {'PASS' if ok else 'FAIL'} "
            f"(live={live}, tests_green={tests_green}, {time.monotonic() - t0:.0f}s)"
        )
    _restore_committed_state()
    threshold = max(cycles - 1, 1)
    verdict = "GATE PASSED" if passes >= threshold else "GATE FAILED — present in replay mode"
    print(f"\n{passes}/{cycles} live passes (threshold {threshold}). {verdict}")
    return 0 if passes >= threshold else 1


def run_harness_rehearsal_gate(cycles: int) -> int:
    """N full live agent-harness cycles from baseline (Option C's beat 4,
    s3_enhancement/harness.py) — the same pass/fail discipline as
    `run_rehearsal_gate` above, extended to the harness path per
    demo/README.md's "S3 live agent-harness beat" section. A cycle passes
    only if the harness ran genuinely live (no replay fallback) — `run_harness`
    already enforces its own independent post-run checks (file-set scope,
    fresh pytest run, content validation) before returning, so a hard
    failure here means one of those checks failed."""
    passes = 0
    print(f"Harness rehearsal gate: {cycles} live harness cycles (tier 'Elite')\n")
    for i in range(1, cycles + 1):
        t0 = time.monotonic()
        _restore_baseline()
        try:
            with _env("HARNESS_MODE", "live"):
                result = run_harness("Elite")
            ok = not result.used_replay
        except HarnessError as exc:
            ok = False
            print(f"  cycle {i}: harness failure: {exc}")
        passes += ok
        print(f"  cycle {i}/{cycles}: {'PASS' if ok else 'FAIL'} ({time.monotonic() - t0:.0f}s)")
    _restore_committed_state()
    threshold = max(cycles - 1, 1)
    verdict = (
        "GATE PASSED"
        if passes >= threshold
        else "GATE FAILED — present S3 without the harness beat (rung 3 pipeline only)"
    )
    print(f"\n{passes}/{cycles} live passes (threshold {threshold}). {verdict}")
    return 0 if passes >= threshold else 1


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


def check_effort_estimate(state: VerificationState) -> str:
    def trial_fn() -> None:
        try:
            estimate = draft_effort_estimate(state.cr_text)
        except LLMError as exc:
            raise AssertionError(f"effort estimate: LLMError: {exc}") from exc
        if not estimate.hours_class.strip():
            raise AssertionError("effort estimate: empty hours_class")
        if estimate.priority_equivalent not in ("P1", "P2", "P3", "P4"):
            raise AssertionError(
                f"effort estimate: priority_equivalent={estimate.priority_equivalent!r} "
                "not one of P1-P4"
            )

    result = run_multi_trial_check("effort estimate structurally sound", trial_fn, trials=5)
    if not result.passed:
        raise AssertionError(result.detail)
    return result.detail


def check_impact_analysis(state: VerificationState) -> str:
    def trial_fn() -> None:
        try:
            text = draft_impact_analysis(state.cr_text)
        except LLMError as exc:
            raise AssertionError(f"impact analysis: LLMError: {exc}") from exc
        _assert_structurally_sound(text, "impact analysis")

    result = run_multi_trial_check("impact analysis structurally sound", trial_fn, trials=5)
    if not result.passed:
        raise AssertionError(result.detail)
    return result.detail


def check_release_notes(state: VerificationState) -> str:
    def trial_fn() -> None:
        try:
            text = draft_release_notes(state.cr_text)
        except LLMError as exc:
            raise AssertionError(f"release notes: LLMError: {exc}") from exc
        _assert_structurally_sound(text, "release notes")
        if not _has_two_distinguishable_parts(text):
            raise AssertionError(
                "release notes: collapsed into a single clause, expected the "
                "release-note + doc-blurb parts asked for in the prompt"
            )

    result = run_multi_trial_check("release notes structurally sound", trial_fn, trials=5)
    if not result.passed:
        raise AssertionError(result.detail)
    return result.detail


def check_cache_hit_on_rerun(state: VerificationState) -> str:
    before_first = snapshot_cache()
    first_start = time.monotonic()
    draft_effort_estimate(state.cr_text)
    draft_impact_analysis(state.cr_text)
    draft_release_notes(state.cr_text)
    first_elapsed = time.monotonic() - first_start
    after_first = snapshot_cache()

    second_start = time.monotonic()
    draft_effort_estimate(state.cr_text)
    draft_impact_analysis(state.cr_text)
    draft_release_notes(state.cr_text)
    second_elapsed = time.monotonic() - second_start
    after_second = snapshot_cache()

    new_on_second = set(after_second) - set(after_first)
    if new_on_second:
        added = ", ".join(str(path) for path in sorted(new_on_second))
        raise AssertionError(
            f"cache-hit rerun added {len(new_on_second)} new cache file(s): {added}"
        )

    first_added = len(set(after_first) - set(before_first))
    return (
        f"first run {first_elapsed:.2f}s, cache-hit rerun {second_elapsed:.2f}s, "
        f"first run added {first_added} cache file(s)"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-live",
        action="store_true",
        help="run only the architecture checks (no live provider calls)",
    )
    parser.add_argument(
        "--gate",
        type=int,
        metavar="N",
        help="run the rehearsal gate: N live codegen cycles, pass threshold N-1",
    )
    parser.add_argument(
        "--harness-gate",
        type=int,
        metavar="N",
        help="run the Option C rehearsal gate: N live agent-harness cycles, pass threshold N-1",
    )
    args = parser.parse_args()

    if args.gate:
        return run_rehearsal_gate(args.gate)
    if args.harness_gate:
        return run_harness_rehearsal_gate(args.harness_gate)

    state = VerificationState()
    results: list[CheckResult] = []

    # Architecture checks first — deterministic, no live model involved. These
    # mutate repos/policycore/tests and restore the committed state afterwards.
    try:
        results.append(
            run_check("replay fully offline", state, check_replay_fully_offline)
        )
        results.append(
            run_check("network-kill mid-codegen fallback", state, check_network_kill_mid_codegen)
        )
        results.append(
            run_check("two tier names from one recording", state, check_two_tier_names_replay)
        )
        results.append(run_check("reset <10s", state, check_reset_speed))
        results.append(
            run_check("S3 relevance keeps core files", state, check_core_recall_never_drops)
        )
        results.append(run_check("S3 relevance ignores decoys", state, check_decoys_never_selected))
        results.append(
            run_check(
                "S3 design-doc gate screens all legacy subsystems",
                state,
                check_design_doc_gate_screens_all_legacy_subsystems,
            )
        )
    finally:
        _restore_committed_state()

    if not args.skip_live:
        # Multi-trial checks require LLM_NO_CACHE=1 — all three functions use a fixed
        # cache_key, but with caching globally disabled every call is a genuine live
        # request regardless of that key, exactly like run_multi_trial_check needs.
        os.environ["LLM_NO_CACHE"] = "1"
        results.append(run_check("effort estimate, 5x live", state, check_effort_estimate))
        results.append(run_check("impact analysis, 5x live", state, check_impact_analysis))
        results.append(run_check("release notes, 5x live", state, check_release_notes))

        # Cache-hit-on-rerun must run with caching enabled.
        os.environ["LLM_NO_CACHE"] = "0"
        results.append(run_check("cache-hit-on-rerun", state, check_cache_hit_on_rerun))

    print_summary(results)
    return 0 if all(result.passed for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
