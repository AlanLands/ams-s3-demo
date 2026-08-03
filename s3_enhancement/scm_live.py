"""Real, local-only git branch creation for Step 0 ("Check out the repo").

`s3_enhancement/scm.py` models the whole branch -> commit -> push flow around
Apply without ever running git — see that module's docstring for why. This
module is the "new module behind an explicit mode flag" its docstring calls
for: it runs real `git` commands, but only when `SCM_MODE=live` is set (the
default, `SCM_MODE` unset, keeps every caller on the fully modelled path —
nothing here executes unless a caller reads `live_mode_enabled()` first).

**Never operates on ams-s3-demo itself.** The target apps live inside this
repo, so branching *here* would branch the whole monorepo — including every
other in-flight change to S3's own code — which is exactly what makes a real
`git checkout -b` unusable in practice (proven directly: it refused the
first time this was tried here, because unrelated uncommitted work on this
repo's dev branch conflicted with `main`). So real checkout always targets a
separate, standalone folder named by `SCM_LIVE_TARGET_ROOT` — a copy of just
the target app, with its own independent git history (or no git history yet
at all; see `_ensure_baseline_commit` below). `_resolve_repo_root` refuses
outright if that path is unset or resolves anywhere inside ams-s3-demo —
structural, not a convention, so a misconfiguration fails loudly instead of
quietly branching the wrong repo.

Scoped deliberately narrow otherwise: **branch creation only.** No `push`,
no `pull`, no `remote`, no `fetch`, no `clone` — a harder-to-reverse follow-
up (a push touches a real remote) that doesn't belong in the same change as
"create a local branch". `commit` gets exactly one narrow exception: turning
a plain folder of files into a git repo needs one commit before `main`
exists as something to branch from at all — that is infrastructure setup,
not the user story workflow's own commit step, and it stays that way structurally:
`tests/test_s3_scm_live.py` AST-walks every git argv literal in this module
and fails if `commit` appears anywhere outside `_ensure_baseline_commit`, or
if any of the other forbidden words appear anywhere at all.

Deliberately stateless, unlike `scm.py`'s persisted `BranchState`. A real
integration would need to remember commits/pushes across requests, but a
branch-only flow doesn't have to: git itself is already the durable state
(`git rev-parse`, `git show-ref`), and Step 0 fires *before* `propose_change`
creates a `proposal_id` to key a state file on in the first place. It also
means every branch this creates always points at the same commit as `main`
— it never diverges — so switching onto or off of one is never a conflict
with uncommitted work elsewhere in the tree; there's no diff to apply.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from s3_enhancement.scm import BASE_BRANCH, branch_name_for

# Used only to *refuse* operating here — never as an operating root. See the
# module docstring for why real git operations must never target this repo.
_AMS_S3_DEMO_ROOT = Path(__file__).resolve().parents[1]

_TARGET_ROOT_ENV = "SCM_LIVE_TARGET_ROOT"
_GIT_TIMEOUT_S = 10


class ScmLiveError(RuntimeError):
    """A `git` command this module ran failed, or its configuration is
    missing/unsafe (see `_resolve_repo_root`)."""


@dataclass(frozen=True)
class LiveCheckoutResult:
    branch: str
    base: str
    sha: str
    created: bool
    already_current: bool
    dirty_files: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "mode": "live",
            "branch": self.branch,
            "base": self.base,
            "sha": self.sha,
            "created": self.created,
            "already_current": self.already_current,
            "dirty_files": list(self.dirty_files),
        }


def live_mode_enabled() -> bool:
    return os.environ.get("SCM_MODE", "simulated").lower() == "live"


def _resolve_repo_root() -> Path:
    """Where real git operations are allowed to run — always an explicit,
    external opt-in, never a default that could silently point at this
    repo."""
    raw = os.environ.get(_TARGET_ROOT_ENV)
    if not raw:
        raise ScmLiveError(
            f"SCM_MODE=live requires {_TARGET_ROOT_ENV} to point at a standalone "
            "app folder — refusing to run real git operations against ams-s3-demo "
            "itself."
        )
    root = Path(raw).expanduser().resolve()
    if not root.is_dir():
        raise ScmLiveError(f"{_TARGET_ROOT_ENV}={raw!r} is not a directory")
    if root == _AMS_S3_DEMO_ROOT or _AMS_S3_DEMO_ROOT in root.parents:
        raise ScmLiveError(
            f"{_TARGET_ROOT_ENV}={raw!r} resolves inside ams-s3-demo itself "
            f"({_AMS_S3_DEMO_ROOT}) — that is exactly what this mode exists to avoid. "
            "Point it at a separate, standalone copy of the target app instead."
        )
    return root


def _git(root: Path, *args: str) -> str:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ScmLiveError(f"git {' '.join(args)} failed to run: {exc}") from exc
    if proc.returncode != 0:
        raise ScmLiveError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def _current_branch(root: Path) -> str:
    return _git(root, "rev-parse", "--abbrev-ref", "HEAD")


def _branch_exists(root: Path, branch: str) -> bool:
    proc = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
        cwd=root,
        capture_output=True,
        timeout=_GIT_TIMEOUT_S,
    )
    return proc.returncode == 0


def _dirty_files(root: Path) -> tuple[str, ...]:
    status = _git(root, "status", "--porcelain")
    if not status:
        return ()
    # Each line is a 2-char status code, a space, then the path.
    return tuple(line[3:] for line in status.splitlines())


def _ensure_baseline_commit(root: Path) -> None:
    """Turn a plain folder of files into a usable git repo: `git init` if
    needed, then exactly one commit if `main` doesn't already resolve to
    something — `git checkout -b <feature> main` needs `main` to point at a
    real commit before there's anything to branch from.

    A no-op whenever `root` is already a real git repo with commits on
    `main` (the common case once the folder has been used once), so this is
    safe to call unconditionally at the top of every `checkout_branch`.

    The one place in this module `commit` legitimately appears — see the
    module docstring and `tests/test_s3_scm_live.py` for why that stays a
    structurally-verified exception rather than a loophole.
    """
    if not (root / ".git").is_dir():
        _git(root, "init", "-b", "main")
    verify = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", "main"],
        cwd=root,
        capture_output=True,
        timeout=_GIT_TIMEOUT_S,
    )
    if verify.returncode != 0:
        _git(root, "add", "-A")
        _git(root, "commit", "--allow-empty", "-m", "Baseline import for live SCM demo")


def checkout_branch(ticket: str, target_id: str) -> LiveCheckoutResult:
    """Create (or switch to) the user story's feature branch in the standalone app
    folder named by `SCM_LIVE_TARGET_ROOT`.

    Idempotent: calling this again for the same ticket/target when already
    on that branch is a no-op that just reports `already_current=True`, the
    same way `scm.open_branch` is idempotent for the modelled flow.
    """
    root = _resolve_repo_root()
    _ensure_baseline_commit(root)
    branch = branch_name_for(ticket, target_id)
    current = _current_branch(root)
    already_current = current == branch
    created = False
    if not already_current:
        if _branch_exists(root, branch):
            _git(root, "checkout", branch)
        else:
            _git(root, "checkout", "-b", branch, BASE_BRANCH)
            created = True
    return LiveCheckoutResult(
        branch=branch,
        base=BASE_BRANCH,
        sha=_git(root, "rev-parse", "--short", "HEAD"),
        created=created,
        already_current=already_current,
        dirty_files=_dirty_files(root),
    )
