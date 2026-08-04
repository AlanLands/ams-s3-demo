"""S3 Option C: live agent-harness codegen, the "money shot" beat.

Where codegen.py/testgen.py concatenate whole mockapp files into one prompt
and ask for complete-file JSON replacements in a single call, this module
shells out to a real headless coding-agent CLI (Claude Code `claude -p` or
Codex CLI `codex exec`) against the actual repo: the harness reads only what
it needs, edits repos/policycore/tests itself, and runs pytest itself, while a
presenter watches it happen live in a terminal.

This is additive only — codegen.py, testgen.py, analyze.py, docgen.py, and
common/llm.py are not touched by this module and remain the deep fallback
(rung 3 of the fallback ladder; see s3_enhancement/README.md).

The harness's own exit code is never trusted as a success signal by itself —
only three independent, objective post-run checks decide success:
1. the working tree's touched-file set is a subset of EXPECTED_FILES,
2. a fresh `pytest tests/test_s3_tier_upgrade.py` run (not whatever the
   harness itself claims it ran) exits 0,
3. a content validator (denylist/secret scan, required public symbols, the
   exact ValueError wordings S4's talk-to-code demo depends on, and the
   models.py backward-compat check) — the same checks codegen.py already
   applies to its own output.

`HARNESS_MODE=live|record|replay` mirrors common/llm.py's `LLM_MODE` naming.
`record` persists a rehearsal run's terminal log and generated file contents
(tier name templated out as the literal `{{TIER_NAME}}` token, exactly like
common/llm.py's stream replay cache) so `replay` can reproduce it offline for
any audience-picked tier name — this is rung 2 of the fallback ladder, kept
deliberately separate from rung 1 (a live failure is a visible terminal
moment; the presenter decides live whether to run the replay).
"""

from __future__ import annotations

import argparse
import ast
import difflib
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from s3_enhancement import targets
from s3_enhancement.story import render_story, sanitize_tier_name
from s3_enhancement.targets import Target

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_ROOT = REPO_ROOT / "s3_enhancement" / "out"
_CACHE_ROOT = REPO_ROOT / "s3_enhancement" / "cache"
REPLAY_PATH = _CACHE_ROOT / "harness_replay.json"

EXPECTED_FILES: tuple[str, ...] = targets.MOCKAPP_TIER_UPGRADE.harness_expected_files


def _replay_path(target: Target) -> Path:
    """Unchanged path for the default target (this file isn't committed, so
    low risk either way); a distinct, namespaced path for any other target so
    two targets' recordings can never collide."""
    if not target.cache_namespace:
        return REPLAY_PATH
    return _CACHE_ROOT / f"harness_replay__{target.cache_namespace}.json"

_TIMEOUT_SECONDS = float(os.environ.get("HARNESS_TIMEOUT_SECONDS", "300"))
_REPLAY_CHUNK_DELAY = 0.02

_SECRET_RE = re.compile(
    r"(sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----)"
)
_DENYLIST = ("real client", "end client", ".env", "api_key", "api key", "secret")
_REQUIRED_TIER_SYMBOLS = ("PLAN_TIERS", "TIER_MULTIPLIERS", "upgrade_tier")
_REQUIRED_ERROR_SUBSTRINGS = ("Unknown plan tier", "not found", "is already at")


class HarnessError(Exception):
    """Raised when a live harness run fails to start, hangs, or fails any
    post-run check. Never auto-caught into a fallback — the caller (CLI or
    Streamlit) decides live whether to move to the next fallback rung."""


@dataclass
class HarnessResult:
    tier_name: str
    diff_text: str
    files_changed: list[str]
    used_replay: bool
    session_log: str
    duration_s: float


# --- prompt / command construction -------------------------------------------


def build_prompt(tier_name: str, story_text: str) -> str:
    return f"""User story:
{story_text}

Audience-selected top tier name: {tier_name}

Follow repos/policycore/CLAUDE.md (or repos/policycore/AGENTS.md — they are content-identical)
in this repo exactly. It is the fixed contract for this change: the file
scope, the exact PLAN_TIERS/TIER_MULTIPLIERS/upgrade_tier API, the
exact ValueError wordings, and the instruction to run pytest before
finishing. Do not re-explore the rest of the repository beyond what that file
points you to — the current file contents are already sufficient context."""


def _build_claude_command(prompt: str) -> list[str]:
    return ["claude", "-p", prompt, "--permission-mode", "bypassPermissions"]


def _build_codex_command(prompt: str) -> list[str]:
    return [
        "codex",
        "exec",
        prompt,
        "-C",
        str(REPO_ROOT),
        "--dangerously-bypass-approvals-and-sandbox",
    ]


_BUILDERS = {"claude": _build_claude_command, "codex": _build_codex_command}


def _resolve_harness() -> str:
    harness = os.environ.get("AGENT_HARNESS", "claude").lower()
    if harness not in _BUILDERS:
        raise HarnessError(f"Unknown AGENT_HARNESS {harness!r}; expected 'claude' or 'codex'")
    return harness


def build_command(tier_name: str, story_text: str) -> tuple[str, list[str]]:
    harness = _resolve_harness()
    prompt = build_prompt(tier_name, story_text)
    return harness, _BUILDERS[harness](prompt)


def _harness_mode() -> str:
    # Default is record, not live: a rehearsal run always leaves a replay
    # recording behind (the demo-day primary), at no extra cost to the run.
    mode = os.environ.get("HARNESS_MODE", "record").lower()
    if mode not in {"live", "record", "replay"}:
        raise HarnessError(f"Unknown HARNESS_MODE {mode!r}; expected 'live', 'record', or 'replay'")
    return mode


# --- process streaming with a hang timeout ------------------------------------


def _stream_process(argv: list[str], log_path: Path, timeout: float) -> tuple[int, str]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    start = time.monotonic()
    try:
        proc = subprocess.Popen(
            argv,
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
            text=True,
            start_new_session=True,
        )
    except FileNotFoundError as exc:
        raise HarnessError(f"harness CLI {argv[0]!r} not found on PATH: {exc}") from exc

    timed_out = False
    with open(log_path, "w", encoding="utf-8") as log_file:
        assert proc.stdout is not None
        for line in proc.stdout:
            print(line, end="", flush=True)
            log_file.write(line)
            lines.append(line)
            if time.monotonic() - start > timeout:
                timed_out = True
                break
        if timed_out:
            _kill_process_group(proc)
        else:
            proc.wait(timeout=10)

    if timed_out:
        raise HarnessError(f"harness run exceeded {timeout:.0f}s timeout and was killed")
    return proc.returncode, "".join(lines)


def _kill_process_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        proc.kill()


# --- objective post-run checks ------------------------------------------------


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout


def _untracked_paths() -> set[str]:
    """Brand-new files with no git history at all (`??` porcelain lines)."""
    porcelain = _git("status", "--porcelain", "--untracked-files=all")
    return {
        line[3:].strip()
        for line in porcelain.splitlines()
        if line.startswith("??") and line.strip()
    }


def _tracked_content_hashes() -> dict[str, str | None]:
    """sha256 per git-tracked path, or None if currently missing from the
    working tree. Content-based (not `git status`'s dirty/clean classification
    relative to HEAD) on purpose: right after demo/reset_s3.sh, mockapp's
    baseline files already differ from HEAD (reset restores the s3-baseline
    tag, not HEAD), so a before/after *dirty-path-set* diff would miss a
    harness run that correctly edits an already-dirty file further. Hashing
    content before and after the run detects real changes regardless of
    whatever state the file was already in when the run started."""
    tracked = [line for line in _git("ls-files").splitlines() if line.strip()]
    hashes: dict[str, str | None] = {}
    for rel_path in tracked:
        path = REPO_ROOT / rel_path
        hashes[rel_path] = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
    return hashes


def _snapshot_expected_files(
    expected_files: tuple[str, ...] = EXPECTED_FILES,
) -> dict[str, str | None]:
    snapshot: dict[str, str | None] = {}
    for rel_path in expected_files:
        path = REPO_ROOT / rel_path
        snapshot[rel_path] = path.read_text(encoding="utf-8") if path.exists() else None
    return snapshot


def _build_diff(
    before: dict[str, str | None], expected_files: tuple[str, ...] = EXPECTED_FILES
) -> str:
    diff_parts: list[str] = []
    for rel_path in expected_files:
        target_path = REPO_ROOT / rel_path
        old_content = before.get(rel_path)
        old = old_content.splitlines(keepends=True) if old_content is not None else []
        new_content = target_path.read_text(encoding="utf-8") if target_path.exists() else ""
        new = new_content.splitlines(keepends=True)
        diff_parts.extend(
            difflib.unified_diff(old, new, fromfile=f"a/{rel_path}", tofile=f"b/{rel_path}")
        )
    return "".join(diff_parts)


def _run_pytest() -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_s3_tier_upgrade.py", "-v"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


def _validate_content(tier_name: str) -> None:
    tiers_path = REPO_ROOT / "repos/policycore/core/tiers.py"
    if not tiers_path.exists():
        raise HarnessError("harness run did not produce repos/policycore/core/tiers.py")
    content = tiers_path.read_text(encoding="utf-8")

    try:
        tree = ast.parse(content, filename=str(tiers_path))
    except SyntaxError as exc:
        raise HarnessError(f"harness generated invalid Python for tiers.py: {exc}") from exc

    lowered = content.lower()
    for forbidden in _DENYLIST:
        if forbidden in lowered:
            raise HarnessError(f"harness generated forbidden string {forbidden!r} in tiers.py")
    if _SECRET_RE.search(content):
        raise HarnessError("harness generated secret-shaped content in tiers.py")

    top_level_names = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
    } | {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    missing = [name for name in _REQUIRED_TIER_SYMBOLS if name not in top_level_names]
    if missing:
        raise HarnessError(
            f"harness tiers.py missing required public symbol(s) {missing} "
            f"— got {sorted(top_level_names)}"
        )

    for substring in _REQUIRED_ERROR_SUBSTRINGS:
        if substring not in content:
            raise HarnessError(f"harness tiers.py missing required error wording {substring!r}")

    if tier_name not in content:
        raise HarnessError(f"harness tiers.py does not mention tier name {tier_name!r}")

    _validate_models_backward_compatible()


def _validate_models_backward_compatible() -> None:
    """repos/policycore/core/seed.py is off the harness's file scope and constructs
    Policy(...) with 6 positional args (no plan_tier) — this must still
    work after the harness's models.py adds plan_tier, or the app crashes
    on startup. Mirrors codegen.py's _validate_policy_backward_compatible."""
    models_path = REPO_ROOT / "repos/policycore/core/models.py"
    models_content = models_path.read_text(encoding="utf-8")
    namespace: dict = {}
    try:
        exec(compile(models_content, "repos/policycore/core/models.py", "exec"), namespace)  # noqa: S102
        policy_cls = namespace["Policy"]
        policy_cls("POL-TEST", "Test Sponsor Ltd.", "Health", 100.0, "2024-01-01", "Active")
    except Exception as exc:
        raise HarnessError(
            "harness generated repos/policycore/core/models.py breaks repos/policycore/core/seed.py's "
            f"existing 6-positional-arg Policy(...) construction: {exc}"
        ) from exc


# --- live run orchestration ---------------------------------------------------


def _run_live(tier_name: str, target: Target) -> HarnessResult:
    story_text = render_story(tier_name, target=target)
    harness, argv = build_command(tier_name, story_text)
    expected_files = target.harness_expected_files

    before_untracked = _untracked_paths()
    before_hashes = _tracked_content_hashes()
    before_content = _snapshot_expected_files(expected_files)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    out_dir = OUT_ROOT / stamp / "harness"
    log_path = out_dir / "session.log"

    # Any HarnessError past this point still leaves a status.json behind, so a
    # failed run stays inspectable (session.log + status) instead of 404ing at
    # /s3/harness/latest as if it never happened.
    try:
        start = time.monotonic()
        returncode, session_log = _stream_process(argv, log_path, _TIMEOUT_SECONDS)
        duration = time.monotonic() - start

        after_untracked = _untracked_paths()
        after_hashes = _tracked_content_hashes()
        new_untracked = after_untracked - before_untracked
        changed_tracked = {
            rel_path for rel_path, before_hash in before_hashes.items()
            if after_hashes.get(rel_path) != before_hash
        }
        touched = new_untracked | changed_tracked
        unexpected = touched - set(expected_files)
        if unexpected:
            raise HarnessError(
                f"harness touched unexpected path(s) {sorted(unexpected)} — "
                f"expected only a subset of {sorted(expected_files)}"
            )
        if not touched:
            raise HarnessError(
                f"harness run finished (exit {returncode}) but touched no files"
            )

        pytest_result = _run_pytest()
        if pytest_result.returncode != 0:
            raise HarnessError(
                "harness-generated tests failed:\n" + pytest_result.stdout + pytest_result.stderr
            )

        _validate_content(tier_name)
    except HarnessError as exc:
        out_dir.mkdir(parents=True, exist_ok=True)
        failed_status = {
            "status": "failed",
            "error": str(exc),
            "tier_name": tier_name,
            "harness": harness,
            "used_replay": False,
            "timestamp": stamp,
        }
        (out_dir / "status.json").write_text(
            json.dumps(failed_status, indent=2), encoding="utf-8"
        )
        raise

    diff_text = _build_diff(before_content, expected_files)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "diff.patch").write_text(diff_text, encoding="utf-8")
    status = {
        "status": "ok",
        "tier_name": tier_name,
        "harness": harness,
        "used_replay": False,
        "returncode": returncode,
        "files_changed": sorted(touched),
        "duration_s": duration,
        "timestamp": stamp,
    }
    (out_dir / "status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")

    return HarnessResult(
        tier_name=tier_name,
        diff_text=diff_text,
        files_changed=sorted(touched),
        used_replay=False,
        session_log=session_log,
        duration_s=duration,
    )


def _record(tier_name: str, target: Target, result: HarnessResult) -> None:
    """Persist a successful live run as the rung-2 fallback recording. The
    tier name is templated out to the literal {{TIER_NAME}} token — same idiom
    as common/llm.py's stream replay cache — so one recording replays for any
    audience-picked name, including in generated file content and diff text."""
    files: dict[str, str] = {}
    for rel_path in target.harness_expected_files:
        path = REPO_ROOT / rel_path
        content = path.read_text(encoding="utf-8") if path.exists() else ""
        files[rel_path] = content.replace(tier_name, "{{TIER_NAME}}")

    replay_path = _replay_path(target)
    replay_path.parent.mkdir(parents=True, exist_ok=True)
    replay_path.write_text(
        json.dumps(
            {
                "session_log": result.session_log.replace(tier_name, "{{TIER_NAME}}"),
                "diff_text": result.diff_text.replace(tier_name, "{{TIER_NAME}}"),
                "files": files,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _replay(tier_name: str, target: Target) -> HarnessResult:
    replay_path = _replay_path(target)
    if not replay_path.exists():
        raise HarnessError(
            f"no harness replay recording at {replay_path} — run with HARNESS_MODE=record first"
        )
    data = json.loads(replay_path.read_text(encoding="utf-8"))

    session_log = str(data["session_log"]).replace("{{TIER_NAME}}", tier_name)
    for chunk_start in range(0, len(session_log), 40):
        chunk = session_log[chunk_start : chunk_start + 40]
        print(chunk, end="", flush=True)
        time.sleep(_REPLAY_CHUNK_DELAY)

    start = time.monotonic()
    for rel_path, templated_content in data["files"].items():
        content = templated_content.replace("{{TIER_NAME}}", tier_name)
        target_path = REPO_ROOT / rel_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(content, encoding="utf-8")

    pytest_result = _run_pytest()
    if pytest_result.returncode != 0:
        raise HarnessError(
            "replayed tests failed — the recording is stale, re-record with "
            "HARNESS_MODE=record:\n" + pytest_result.stdout + pytest_result.stderr
        )
    _validate_content(tier_name)
    duration = time.monotonic() - start

    diff_text = str(data["diff_text"]).replace("{{TIER_NAME}}", tier_name)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    out_dir = OUT_ROOT / stamp / "harness"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "diff.patch").write_text(diff_text, encoding="utf-8")
    status = {
        "tier_name": tier_name,
        "harness": "replay",
        "used_replay": True,
        "files_changed": sorted(data["files"]),
        "duration_s": duration,
        "timestamp": stamp,
    }
    (out_dir / "status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")

    return HarnessResult(
        tier_name=tier_name,
        diff_text=diff_text,
        files_changed=sorted(data["files"]),
        used_replay=True,
        session_log=session_log,
        duration_s=duration,
    )


def run_harness(tier_name: str, *, target: Target | None = None) -> HarnessResult:
    """Rung 1 (or record-mode rung 1): run the harness live. Never falls back
    to replay on its own — a HarnessError here is a presenter-visible live
    failure; the presenter decides whether to run `replay_harness` next."""
    target = target or targets.get_target(None)
    mode = _harness_mode()
    if mode == "replay":
        return _replay(tier_name, target)
    result = _run_live(tier_name, target)
    if mode == "record":
        _record(tier_name, target, result)
    return result


def replay_harness(tier_name: str, *, target: Target | None = None) -> HarnessResult:
    """Rung 2, explicitly presenter-triggered."""
    target = target or targets.get_target(None)
    return _replay(tier_name, target)


def latest_harness_run() -> Path | None:
    """Most recent s3_enhancement/out/<timestamp>/harness/ directory, or None."""
    if not OUT_ROOT.exists():
        return None
    candidates = sorted(OUT_ROOT.glob("*/harness"), key=lambda p: p.parent.name, reverse=True)
    return candidates[0] if candidates else None


# --- CLI -----------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser(
        "run", help="run the harness (live or record, per HARNESS_MODE)"
    )
    run_parser.add_argument("--tier-name", required=True)
    run_parser.add_argument(
        "--target", default=None, help="registered target id (default: the demo target)"
    )

    replay_parser = subparsers.add_parser(
        "replay", help="explicitly replay the rehearsed recording"
    )
    replay_parser.add_argument("--tier-name", required=True)
    replay_parser.add_argument(
        "--target", default=None, help="registered target id (default: the demo target)"
    )

    args = parser.parse_args()
    tier_name, error = sanitize_tier_name(args.tier_name)
    if error:
        print(f"FAIL: invalid --tier-name: {error}", file=sys.stderr)
        return 1

    target = targets.get_target(args.target)
    try:
        if args.command == "run":
            result = run_harness(tier_name, target=target)
        else:
            result = replay_harness(tier_name, target=target)
    except HarnessError as exc:
        print(f"\n\nFAIL: {exc}", file=sys.stderr)
        return 1

    print(f"\n\nOK: {result.files_changed} changed in {result.duration_s:.1f}s "
          f"(used_replay={result.used_replay})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
