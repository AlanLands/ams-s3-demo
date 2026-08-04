"""Verifies s3_enhancement/scm_live.py — the real, local-only branch-creation
flow behind SCM_MODE=live.

Unlike tests/test_s3_scm.py, this module *is* allowed to run git. What it
must never be able to do is push, pull, fetch, clone, or touch a remote —
and it must never run any of that against ams-s3-demo itself, only against
the standalone folder named by SCM_LIVE_TARGET_ROOT. `commit` gets exactly
one narrow, structurally-verified exception: bootstrapping a plain folder of
files into a git repo needs one commit before `main` exists as something to
branch from. Asserted on the parsed AST, the same way test_s3_scm.py
protects scm.py, so the guardrails survive even as this module grows.

Functional tests run against real throwaway folders under tmp_path, never
against this project's own repo.
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest

from s3_enhancement import scm, scm_live
from s3_enhancement.scm_live import ScmLiveError, checkout_branch, live_mode_enabled

SCM_LIVE_SOURCE = Path(scm_live.__file__)

_ALWAYS_FORBIDDEN = {"push", "pull", "remote", "fetch", "clone"}
_COMMIT_ALLOWED_IN = "_ensure_baseline_commit"


def _collect_git_argv_by_function() -> dict[str, list[list[str]]]:
    """Every literal argv list this module could pass to `git`, grouped by
    the function it appears in — from both the `_git(root, *args)` helper's
    call sites and the raw `subprocess.run` calls elsewhere in the module."""
    tree = ast.parse(SCM_LIVE_SOURCE.read_text(encoding="utf-8"))

    def string_args(call: ast.Call) -> list[str]:
        return [arg.value for arg in call.args if isinstance(arg, ast.Constant)]

    by_function: dict[str, list[list[str]]] = {}
    for func_node in ast.walk(tree):
        if not isinstance(func_node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        argvs: list[list[str]] = []
        for node in ast.walk(func_node):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if isinstance(f, ast.Name) and f.id == "_git":
                argvs.append(string_args(node))
            elif isinstance(f, ast.Attribute) and f.attr == "run":
                if node.args and isinstance(node.args[0], ast.List):
                    elts = node.args[0].elts
                    argvs.append([e.value for e in elts if isinstance(e, ast.Constant)])
        by_function[func_node.name] = argvs
    return by_function


# --- the never-push / commit-confined-to-bootstrap guarantee -----------------


def test_no_argv_ever_requests_a_push_pull_remote_fetch_or_clone():
    by_function = _collect_git_argv_by_function()
    all_argvs = [argv for argvs in by_function.values() for argv in argvs]
    assert all_argvs, "expected at least one git argv literal to check"
    offenders = [argv for argv in all_argvs if set(argv) & _ALWAYS_FORBIDDEN]
    assert not offenders, (
        f"{SCM_LIVE_SOURCE.name} must never push/pull/fetch/clone or touch a remote: "
        f"found forbidden git argv(s) {offenders}"
    )


def test_commit_only_ever_appears_in_the_one_time_baseline_bootstrap():
    by_function = _collect_git_argv_by_function()
    offenders = [
        (func_name, argv)
        for func_name, argvs in by_function.items()
        for argv in argvs
        if "commit" in argv and func_name != _COMMIT_ALLOWED_IN
    ]
    assert not offenders, (
        f"{SCM_LIVE_SOURCE.name} must confine `git commit` to "
        f"{_COMMIT_ALLOWED_IN} (the one-time bootstrap) — found it in {offenders}"
    )
    assert any("commit" in argv for argv in by_function.get(_COMMIT_ALLOWED_IN, [])), (
        f"expected {_COMMIT_ALLOWED_IN} to actually contain a commit call to check"
    )


def test_module_never_imports_network_or_credential_machinery():
    """No GitHub API client, no requests/httpx, no credential helpers — this
    module only ever shells out to the local `git` binary."""
    tree = ast.parse(SCM_LIVE_SOURCE.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    forbidden = {"requests", "httpx", "urllib", "github", "PyGithub"}
    assert not (imported & forbidden), (
        f"{SCM_LIVE_SOURCE.name} must only talk to local git, never a remote "
        f"API — it imports {sorted(imported & forbidden)}"
    )


# --- live_mode_enabled --------------------------------------------------------


def test_live_mode_disabled_by_default(monkeypatch):
    monkeypatch.delenv("SCM_MODE", raising=False)
    assert live_mode_enabled() is False


def test_live_mode_enabled_when_set(monkeypatch):
    monkeypatch.setenv("SCM_MODE", "live")
    assert live_mode_enabled() is True


def test_live_mode_disabled_for_any_other_value(monkeypatch):
    monkeypatch.setenv("SCM_MODE", "simulated")
    assert live_mode_enabled() is False


# --- _resolve_repo_root: the never-touch-ams-s3-demo guarantee ---------------


def test_checkout_refuses_when_target_root_is_unset(monkeypatch):
    monkeypatch.delenv("SCM_LIVE_TARGET_ROOT", raising=False)
    with pytest.raises(ScmLiveError, match="SCM_LIVE_TARGET_ROOT"):
        checkout_branch("AMS-1046", "documenthub-rostered-guest-wording")


def test_checkout_refuses_when_target_root_is_ams_s3_demo_itself(monkeypatch):
    monkeypatch.setenv("SCM_LIVE_TARGET_ROOT", str(scm_live._AMS_S3_DEMO_ROOT))
    with pytest.raises(ScmLiveError, match="ams-s3-demo itself"):
        checkout_branch("AMS-1046", "documenthub-rostered-guest-wording")


def test_checkout_refuses_when_target_root_is_nested_inside_ams_s3_demo(monkeypatch):
    nested = scm_live._AMS_S3_DEMO_ROOT / "repos" / "policycore"
    monkeypatch.setenv("SCM_LIVE_TARGET_ROOT", str(nested))
    with pytest.raises(ScmLiveError, match="ams-s3-demo itself"):
        checkout_branch("AMS-1046", "documenthub-rostered-guest-wording")


def test_checkout_refuses_when_target_root_does_not_exist(tmp_path, monkeypatch):
    monkeypatch.setenv("SCM_LIVE_TARGET_ROOT", str(tmp_path / "nowhere"))
    with pytest.raises(ScmLiveError, match="not a directory"):
        checkout_branch("AMS-1046", "documenthub-rostered-guest-wording")


# --- checkout_branch, against real throwaway folders --------------------------


def _current_branch(root: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--abbrev-ref", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.fixture
def plain_folder(tmp_path, monkeypatch):
    """A folder of ordinary files with no git history at all — the realistic
    case: a standalone copy of just the target app, dropped in place."""
    (tmp_path / "app.py").write_text("print('hello')\n", encoding="utf-8")
    monkeypatch.setenv("SCM_LIVE_TARGET_ROOT", str(tmp_path))
    return tmp_path


@pytest.fixture
def git_repo(tmp_path, monkeypatch):
    """A folder that's already a real git repo — `main` with one commit —
    to check the bootstrap is a no-op once history already exists."""
    subprocess.run(["git", "init", "-b", "main", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "demo@example.com"], check=True
    )
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Demo"], check=True)
    (tmp_path / "README.md").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "README.md"], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-m", "initial"], check=True, capture_output=True
    )
    monkeypatch.setenv("SCM_LIVE_TARGET_ROOT", str(tmp_path))
    return tmp_path


def test_bootstraps_a_plain_folder_into_a_git_repo(plain_folder):
    result = checkout_branch("AMS-1046", "documenthub-rostered-guest-wording")
    assert (plain_folder / ".git").is_dir()
    assert result.branch == scm.branch_name_for("AMS-1046", "documenthub-rostered-guest-wording")
    assert result.created is True
    assert _current_branch(plain_folder) == result.branch


def test_bootstrap_produces_exactly_one_baseline_commit(plain_folder):
    checkout_branch("AMS-1046", "documenthub-rostered-guest-wording")
    log = subprocess.run(
        ["git", "-C", str(plain_folder), "log", "--oneline", "main"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip().splitlines()
    assert len(log) == 1
    assert "Baseline import" in log[0]


def test_bootstrap_is_a_no_op_when_history_already_exists(git_repo):
    before = subprocess.run(
        ["git", "-C", str(git_repo), "rev-parse", "main"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    checkout_branch("AMS-1046", "documenthub-rostered-guest-wording")
    after_log = subprocess.run(
        ["git", "-C", str(git_repo), "log", "--oneline", "main"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip().splitlines()
    # Still just the one commit the fixture made — bootstrap did not add another.
    assert len(after_log) == 1
    switch_back = subprocess.run(
        ["git", "-C", str(git_repo), "rev-parse", "main"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert before == switch_back


def test_creates_a_new_branch_off_main(git_repo):
    result = checkout_branch("AMS-1046", "documenthub-rostered-guest-wording")
    assert result.branch == scm.branch_name_for("AMS-1046", "documenthub-rostered-guest-wording")
    assert result.base == "main"
    assert result.created is True
    assert result.already_current is False
    assert _current_branch(git_repo) == result.branch


def test_idempotent_when_already_on_the_branch(git_repo):
    first = checkout_branch("AMS-1046", "documenthub-rostered-guest-wording")
    second = checkout_branch("AMS-1046", "documenthub-rostered-guest-wording")
    assert second.branch == first.branch
    assert second.created is False
    assert second.already_current is True


def test_switches_back_to_an_existing_branch(git_repo):
    checkout_branch("AMS-1046", "documenthub-rostered-guest-wording")
    subprocess.run(["git", "-C", git_repo, "checkout", "main"], check=True, capture_output=True)
    assert _current_branch(git_repo) == "main"

    result = checkout_branch("AMS-1046", "documenthub-rostered-guest-wording")
    assert result.created is False
    assert result.already_current is False
    assert _current_branch(git_repo) == result.branch


def test_reports_dirty_files_without_blocking(git_repo):
    (git_repo / "scratch.txt").write_text("uncommitted\n", encoding="utf-8")
    result = checkout_branch("AMS-1046", "documenthub-rostered-guest-wording")
    assert "scratch.txt" in result.dirty_files
    # Dirty files are informational only — checkout still succeeds.
    assert result.created is True


def test_clean_tree_reports_no_dirty_files(git_repo):
    result = checkout_branch("AMS-1046", "documenthub-rostered-guest-wording")
    assert result.dirty_files == ()


def test_sha_matches_real_head(git_repo):
    result = checkout_branch("AMS-1046", "documenthub-rostered-guest-wording")
    real_sha = subprocess.run(
        ["git", "-C", str(git_repo), "rev-parse", "--short", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert result.sha == real_sha
