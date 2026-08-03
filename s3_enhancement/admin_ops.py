"""Operations behind the console's admin panel: demo-state resets, target-app
process control, and repo onboarding.

Everything the presenter would otherwise open a terminal for. Three rules
shape this module, and all three are load-bearing:

**1. A reset must never silently discard work.** `demo/reset_s3.sh` and
`demo/reset_s3_endorsement.sh` restore source with `git checkout HEAD -- …`,
and the ClaimsPortal/EnrolDirect resets overwrite source from their committed
`.baseline/` snapshots. Over a terminal that is a considered act; over HTTP it
is a button. So every source-restoring scope is previewed against
`git status` first (`scope_preview`) and refused outright while the paths it
would overwrite are dirty (`scope_blockers`). Delete-only scopes touch nothing
but generated state and stay allowed.

**2. Never build a shell command by string interpolation.** Reset scripts run
as `[bash, <absolute script path>]` with a fixed argument list and no shell;
the delete-only scopes are reimplemented in Python and never shell out at all.
Git runs the same way. Nothing here interpolates a caller-supplied value into
a command.

**3. Report what is true, not what was attempted.** `up` is a plain TCP
connect to `localhost:<port>` — no `ps`, no `lsof`, no `/proc` — so it works
in the locked-down environment CLAUDE.md hard rule #4 requires. After a
start/stop the port is re-probed and the *probe* decides `ok`, not the
`Popen`/`kill` return. Where process control genuinely is not available (no
PID file for a service someone started by hand, spawning refused) the answer
is `ok: False` plus the exact command an operator should run. Same rule
`s3_enhancement/scm.py` follows for `simulated`: the honest "no" beats an
unverified "yes".

The known live breakage this module has to survive: the `apps/` -> `repos/`
move is uncommitted, so the paths `demo/reset_s3.sh` checks out
(`repos/policycore/app.py`, …) do not exist in HEAD yet — HEAD still carries
them under `apps/`. `git checkout HEAD -- repos/policycore/app.py` therefore
dies with "pathspec did not match". `head_missing_paths()` detects that with
`git cat-file -e HEAD:<path>` and it surfaces as a named
`reset_blocked_reason` instead of a raw git error out of a button.
"""

from __future__ import annotations

import os
import re
import shutil
import signal
import socket
import subprocess
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[1]

# Overridable so tests can point the whole module at a `tmp_path` fixture.
# Nothing here may run against the real working tree under test — a previous
# pass at this feature ran `git stash` in the live repo, which is exactly the
# accident the reset gate exists to prevent.
REPO_ROOT_ENV = "S3_ADMIN_REPO_ROOT"

# Set to "off"/"0"/"false" where the console has no business spawning
# processes (a hardened host, a container without job control). Start/stop
# then answer `ok: False` with the command to run by hand rather than
# pretending.
PROCESS_CONTROL_ENV = "S3_ADMIN_PROCESS_CONTROL"

MANIFEST_NAME = ".s3targets.json"


def repo_root() -> Path:
    return Path(os.environ.get(REPO_ROOT_ENV, _DEFAULT_REPO_ROOT))


def _rel(path: Path) -> str:
    """POSIX-style repo-relative path — the form every response uses, and the
    form git pathspecs take."""
    try:
        return path.resolve().relative_to(repo_root().resolve()).as_posix()
    except ValueError:
        return path.as_posix()


# ---------------------------------------------------------------------------
# git — read-only. Nothing in this module writes to the working tree via git.
# ---------------------------------------------------------------------------


class GitUnavailable(RuntimeError):
    """git is missing, or this is not a work tree."""


def _git(*args: str, check: bool = False) -> subprocess.CompletedProcess:
    """Run one git command with a fixed argument list, no shell.

    `args` is only ever module-owned literals plus repo-relative pathspecs
    from the frozen scope table — never a value a caller supplied.
    """
    git = shutil.which("git") or "/usr/bin/git"
    return subprocess.run(  # noqa: S603 - fixed argv, shell=False
        [git, *args],
        cwd=str(repo_root()),
        capture_output=True,
        text=True,
        check=check,
        timeout=60,
    )


def current_branch() -> str:
    result = _git("rev-parse", "--abbrev-ref", "HEAD")
    if result.returncode != 0:
        raise GitUnavailable(result.stderr.strip() or "git rev-parse failed")
    return result.stdout.strip()


def default_branch_name() -> str:
    """The branch resets treat as home. `main` unless the repo says otherwise."""
    result = _git("symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip().split("/")[-1]
    return "main"


def _porcelain(pathspecs: Sequence[str] | None = None) -> list[str]:
    """`git status --porcelain -uall`, optionally narrowed to pathspecs.

    `-uall` rather than the default `normal` on purpose: the default collapses
    a wholly-untracked directory to one line (`?? repos/`), which would both
    undercount `dirty_file_count` and hide every individual file a scope is
    about to overwrite.
    """
    extra = ["--", *pathspecs] if pathspecs else []
    result = _git("status", "--porcelain", "--untracked-files=all", *extra)
    if result.returncode != 0:
        raise GitUnavailable(result.stderr.strip() or "git status failed")
    return [line for line in result.stdout.splitlines() if line.strip()]


def _porcelain_status(pathspecs: Sequence[str] | None = None) -> dict[str, str]:
    """path -> two-character porcelain status code."""
    statuses: dict[str, str] = {}
    for line in _porcelain(pathspecs):
        code, entry = line[:2], line[3:] if len(line) > 3 else ""
        # Rename/copy entries read "old -> new"; the new path is the one on disk.
        if " -> " in entry:
            entry = entry.split(" -> ", 1)[1]
        entry = entry.strip().strip('"')
        if entry:
            statuses[entry] = code
    return statuses


def dirty_file_count() -> int:
    return len(_porcelain())


def dirty_among(paths: Iterable[str], *, include_untracked: bool = True) -> list[str]:
    """Which of `paths` git currently reports as uncommitted.

    Gitignored generated state (`data/*`, `.cache/`, `s3_enhancement/out/`)
    never appears — that is the point. Deleting a regenerable artifact is not
    losing work, and a delete-only scope must not be blocked by one.

    `include_untracked=False` narrows to tracked-but-modified. Used for the
    files a scope *deletes*: those live at paths the pipeline generates into
    (`tests/test_s3_*.py`, `core/tiers.py`), so they are untracked by nature
    and blocking on them would make the reset button unusable exactly after a
    rehearsal, which is when it is needed. A tracked file with real edits at
    one of those paths still counts — that is somebody's work.
    """
    wanted = [p for p in dict.fromkeys(paths) if p]
    if not wanted:
        return []
    statuses = _porcelain_status(wanted)
    if not include_untracked:
        statuses = {p: c for p, c in statuses.items() if c != "??"}
    reported = set(statuses)
    # A pathspec that is a directory reports its children; keep both forms.
    dirty = [p for p in wanted if p in reported or any(r.startswith(p + "/") for r in reported)]
    return sorted(dirty)


def head_has_path(rel_path: str) -> bool:
    """Does `HEAD:<rel_path>` resolve? The check that catches the live
    `repos/` vs `apps/` breakage before a button hits it."""
    return _git("cat-file", "-e", f"HEAD:{rel_path}").returncode == 0


# ---------------------------------------------------------------------------
# Reset scopes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Scope:
    """One reset scope, describing exactly what it touches.

    `restores_source` splits the two kinds. Source scopes overwrite files a
    human may have edited and are gated; state scopes delete only regenerable
    artifacts and are always allowed. `head_paths` are restored by
    `git checkout HEAD --` and so additionally require the path to exist in
    HEAD; `baseline_restores` are `cp`-from-`.baseline/` and do not.
    """

    id: str
    restores_source: bool
    detail: str
    scripts: tuple[str, ...] = ()
    head_paths: tuple[str, ...] = ()
    index_globs: tuple[str, ...] = ()
    baseline_restores: tuple[str, ...] = ()
    delete_paths: tuple[str, ...] = ()
    delete_globs: tuple[str, ...] = ()
    # Directories whose *contents* are removed, the directory itself kept.
    delete_tree_contents: tuple[str, ...] = ()
    # Directories removed outright.
    delete_trees: tuple[str, ...] = ()
    ran_labels: tuple[str, ...] = ()
    writes_reset_marker: bool = True


# The PolicyCore scope runs both of that target's reset scripts. PolicyCore
# hosts two user stories (US-2026-041 plan tier, US-2026-042 amendment field) and each
# has its own script; restoring only one leaves the other user story's edits — most
# visibly core/amendments.py — in the tree, which is precisely the
# half-restored state that surfaces mid-rehearsal rather than at the button.
SCOPES: dict[str, Scope] = {
    "policycore": Scope(
        id="policycore",
        restores_source=True,
        scripts=("demo/reset_s3.sh", "demo/reset_s3_endorsement.sh"),
        ran_labels=("demo/reset_s3.sh", "demo/reset_s3_endorsement.sh"),
        head_paths=(
            "repos/policycore/app.py",
            "repos/policycore/core/models.py",
            "repos/policycore/core/db.py",
            "repos/policycore/core/amendments.py",
        ),
        # reset_s3.sh restores the committed per-issue Jira replay caches, so
        # every rehearsal starts from the seeded board rather than wherever
        # the last run left it. Listed because it is a source restore too.
        index_globs=("s3_enhancement/cache/jira_*.json",),
        delete_paths=(
            "repos/policycore/core/tiers.py",
            "tests/test_s3_tier_upgrade.py",
            "tests/test_s3_amendment_priority.py",
            "data/ticket_events.jsonl",
        ),
        delete_tree_contents=("s3_enhancement/out",),
        delete_trees=(".cache/llm",),
        detail=(
            "PolicyCore source restored from HEAD (both user stories), database reseeded, "
            "generated files removed, LLM cache / staged proposals / ticket timeline cleared."
        ),
    ),
    "claimsportal": Scope(
        id="claimsportal",
        restores_source=True,
        scripts=("demo/reset_s3_claimsportal.sh",),
        ran_labels=("demo/reset_s3_claimsportal.sh",),
        baseline_restores=(
            "repos/claimsportal/policy_service/policy.py",
            "repos/claimsportal/policy_service/main.py",
            "repos/claimsportal/claims_service/claim.py",
            "repos/claimsportal/claims_service/policy_client.py",
            "repos/claimsportal/claims_service/main.py",
        ),
        delete_paths=(
            "repos/claimsportal/claims_service/claim_rules.py",
            "tests/test_s3_claims_deductible.py",
        ),
        detail=(
            "ClaimsPortal source restored from its committed .baseline/ snapshot; "
            "generated files removed. Staged proposals are shared across targets — "
            "run the proposals scope too for a full between-rehearsals reset."
        ),
    ),
    "enroldirect": Scope(
        id="enroldirect",
        restores_source=True,
        scripts=("demo/reset_s3_enroldirect.sh",),
        ran_labels=("demo/reset_s3_enroldirect.sh",),
        baseline_restores=(
            "repos/enroldirect/applicants.py",
            "repos/enroldirect/eligibility.py",
            "repos/enroldirect/enrolments.py",
            "repos/enroldirect/main.py",
        ),
        delete_paths=("tests/test_s3_prospect_access.py",),
        detail=(
            "EnrolDirect source restored from its committed .baseline/ snapshot "
            "(the baseline is a removal — prospects are refused); generated tests removed."
        ),
    ),
    "tickets": Scope(
        id="tickets",
        restores_source=False,
        delete_paths=("data/ticket_events.jsonl",),
        detail="Ticket board reset.",
    ),
    "logs": Scope(
        id="logs",
        restores_source=False,
        delete_globs=("data/*.jsonl", "logs/*.log", "data/logs/*.log"),
        detail="Log files cleared.",
    ),
    "proposals": Scope(
        id="proposals",
        restores_source=False,
        delete_tree_contents=("s3_enhancement/out",),
        detail="Staged proposals, backups, rejections and SCM state cleared.",
    ),
    # `.cache/vectordb` is deliberately NOT in here. It is the relevance
    # embedding index, and rebuilding it can mean live embedding calls — the
    # opposite of what a mid-demo reset button should risk. The committed
    # replay recordings under s3_enhancement/cache/ are likewise untouched:
    # deleting those turns every beat into a live call.
    "caches": Scope(
        id="caches",
        restores_source=False,
        delete_trees=(".cache/llm",),
        detail="LLM response cache cleared. Committed replay recordings untouched.",
    ),
}

SOURCE_SCOPES = tuple(s.id for s in SCOPES.values() if s.restores_source)


def _resolve_globs(globs: Iterable[str]) -> list[str]:
    root = repo_root()
    out: list[str] = []
    for pattern in globs:
        parent, _, leaf = pattern.rpartition("/")
        base = root / parent if parent else root
        if not base.is_dir():
            continue
        out += [_rel(p) for p in sorted(base.glob(leaf)) if p.is_file()]
    return out


def scope_restores(scope: Scope) -> list[str]:
    """Every path the scope overwrites. Listed whether or not it exists on
    disk — a restore writes regardless."""
    paths = [*scope.head_paths, *scope.baseline_restores, *_resolve_globs(scope.index_globs)]
    return sorted(dict.fromkeys(paths))


def scope_deletes(scope: Scope) -> list[str]:
    """Every path the scope removes, filtered to what actually exists — the
    preview answers "what would this delete", not "what might it have"."""
    root = repo_root()
    paths = [p for p in scope.delete_paths if (root / p).exists()]
    paths += _resolve_globs(scope.delete_globs)
    for tree in scope.delete_tree_contents:
        base = root / tree
        if base.is_dir():
            paths += [_rel(child) for child in sorted(base.iterdir())]
    for tree in scope.delete_trees:
        if (root / tree).exists():
            paths.append(tree)
    return sorted(dict.fromkeys(paths))


def scope_preview(scope_id: str) -> dict[str, Any]:
    scope = SCOPES[scope_id]
    restores = scope_restores(scope)
    deletes = scope_deletes(scope)
    # Both halves are destructive, so both are checked — a restore overwrites
    # an edited file, and a delete of a tracked, modified file loses the same
    # work — but with different thresholds. See `dirty_among` for why an
    # untracked file only counts on the restore side.
    dirty = dirty_among(restores) + dirty_among(deletes, include_untracked=False)
    return {
        "scope": scope_id,
        "restores": restores,
        "deletes": deletes,
        "dirty": sorted(dict.fromkeys(dirty)),
    }


def head_missing_paths(scope_ids: Iterable[str] | None = None) -> list[str]:
    """`git checkout HEAD --` paths that HEAD does not carry.

    Today this returns the four `repos/policycore/...` paths: the move out of
    `apps/` is staged in nobody's commit yet, so HEAD still has them under
    `apps/` and the checkout fails with "pathspec did not match any file(s)
    known to git". Detected here so it reads as a named blocked reason rather
    than a raw git error surfacing out of a button.
    """
    ids = list(scope_ids) if scope_ids is not None else list(SCOPES)
    missing: list[str] = []
    for scope_id in ids:
        for path in SCOPES[scope_id].head_paths:
            if not head_has_path(path):
                missing.append(path)
    return sorted(dict.fromkeys(missing))


def scope_blockers(scope_id: str) -> list[str]:
    """Why this scope must not run. Empty means it may."""
    scope = SCOPES[scope_id]
    if not scope.restores_source:
        return []
    blockers: list[str] = []
    missing = head_missing_paths([scope_id])
    if missing:
        shown = ", ".join(missing[:4])
        more = f" (+{len(missing) - 4} more)" if len(missing) > 4 else ""
        blockers.append(
            f"{len(missing)} path(s) restored by this scope do not exist in HEAD "
            f"— {shown}{more}. The repos/ move is uncommitted, so "
            f"`git checkout HEAD -- <path>` fails with 'pathspec did not match'. "
            f"Commit the move, or run the reset from a terminal."
        )
    dirty = scope_preview(scope_id)["dirty"]
    if dirty:
        shown = ", ".join(dirty[:4])
        more = f" (+{len(dirty) - 4} more)" if len(dirty) > 4 else ""
        blockers.append(
            f"{len(dirty)} file(s) this scope would overwrite have uncommitted "
            f"changes — {shown}{more}. The reset restores them from HEAD/.baseline "
            f"and the changes would be lost."
        )
    return blockers


def reset_safety() -> tuple[bool, str | None]:
    """The global gate `GET /api/admin/status` reports.

    Safe only when *every* source-restoring scope could run right now. The
    per-scope check in `scope_blockers` is the precise one; this is the
    summary the UI disables its buttons on.
    """
    reasons: list[str] = []
    for scope_id in SOURCE_SCOPES:
        reasons += scope_blockers(scope_id)
    if not reasons:
        return True, None
    total_dirty = dirty_file_count()
    summary = "; ".join(reasons)
    return False, f"{summary} Working tree has {total_dirty} uncommitted file(s) in total."


# ---------------------------------------------------------------------------
# Running a reset
# ---------------------------------------------------------------------------


class ResetFailed(RuntimeError):
    def __init__(self, message: str, output: str = "") -> None:
        super().__init__(message)
        self.output = output


def _bash() -> str:
    return shutil.which("bash") or "/bin/bash"


def _touch_reset_marker() -> None:
    """Bump the marker the console's client-side cache watches, so a reset
    invalidates stale per-ticket results in the browser (see
    common.ticket_events.events_log_marker)."""
    root = repo_root()
    marker = root / "data" / ".s3_reset_marker"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(f"{time.time_ns()}\n", encoding="utf-8")


def run_reset(scope_id: str) -> dict[str, Any]:
    """Execute a scope. Caller must have checked `scope_blockers` first."""
    scope = SCOPES[scope_id]
    ran: list[str] = []

    for script in scope.scripts:
        script_path = (repo_root() / script).resolve()
        if not script_path.is_file():
            raise ResetFailed(f"reset script not found: {script}")
        # Fixed argv, shell=False, absolute path. Nothing interpolated.
        result = subprocess.run(  # noqa: S603
            [_bash(), str(script_path)],
            cwd=str(repo_root()),
            capture_output=True,
            text=True,
            timeout=600,
        )
        ran.append(script)
        if result.returncode != 0:
            tail = (result.stderr or result.stdout).strip().splitlines()
            raise ResetFailed(
                f"{script} exited {result.returncode}",
                "\n".join(tail[-12:]),
            )

    if not scope.scripts:
        ran += _run_state_scope(scope)

    if scope.writes_reset_marker:
        _touch_reset_marker()

    return {"scope": scope_id, "ran": ran, "detail": scope.detail, "simulated": False}


def _run_state_scope(scope: Scope) -> list[str]:
    """Delete-only scopes, reimplemented in Python — no shell at all."""
    root = repo_root()
    ran: list[str] = []
    for rel_path in scope.delete_paths:
        target = root / rel_path
        if target.is_file():
            target.unlink()
            ran.append(f"rm -f {rel_path}")
    for rel_path in _resolve_globs(scope.delete_globs):
        target = root / rel_path
        if target.is_file():
            target.unlink()
            ran.append(f"rm -f {rel_path}")
    for tree in scope.delete_tree_contents:
        base = root / tree
        if base.is_dir():
            for child in sorted(base.iterdir()):
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
            ran.append(f"rm -rf {tree}/*")
    for tree in scope.delete_trees:
        base = root / tree
        if base.is_dir():
            shutil.rmtree(base)
            ran.append(f"rm -rf {tree}")
        elif base.is_file():
            base.unlink()
            ran.append(f"rm -f {tree}")
    return ran


# ---------------------------------------------------------------------------
# Log files
# ---------------------------------------------------------------------------

LOG_GLOBS: tuple[str, ...] = SCOPES["logs"].delete_globs


def log_files() -> list[dict[str, Any]]:
    root = repo_root()
    files: list[dict[str, Any]] = []
    for rel_path in _resolve_globs(LOG_GLOBS):
        path = root / rel_path
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        files.append(
            {
                "path": rel_path,
                "bytes": len(raw),
                "lines": raw.count(b"\n") + (1 if raw and not raw.endswith(b"\n") else 0),
            }
        )
    return files


def delete_log_files() -> dict[str, Any]:
    root = repo_root()
    deleted: list[str] = []
    freed = 0
    for entry in log_files():
        path = root / entry["path"]
        try:
            path.unlink()
        except OSError:
            continue
        deleted.append(entry["path"])
        freed += entry["bytes"]
    if deleted:
        _touch_reset_marker()
    return {"deleted": deleted, "bytes_freed": freed}


# ---------------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Service:
    id: str
    label: str
    port_env: str
    default_port: int
    command: str


# Ports mirror the launch scripts' own defaults and the same .env variables
# they read, so the TCP probe hits the port the app would actually bind.
SERVICES: tuple[Service, ...] = (
    Service("policycore", "PolicyCore portal", "PORT", 8501, "demo/run_mockapp.sh"),
    Service(
        "policy_service",
        "ClaimsPortal — contracts",
        "POLICY_SERVICE_PORT",
        8081,
        "apps/run-policy-service.sh",
    ),
    Service(
        "claims_service",
        "ClaimsPortal — claims",
        "CLAIMS_SERVICE_PORT",
        8082,
        "apps/run-claims-service.sh",
    ),
    Service("enroldirect", "EnrolDirect", "ENROLDIRECT_PORT", 8083, "apps/run-enroldirect.sh"),
)

SERVICES_BY_ID: dict[str, Service] = {s.id: s for s in SERVICES}

# The console cannot restart the process serving the request. Naming any of
# these is a 400, not an attempt — an attempt would kill the connection the
# answer travels on.
CONSOLE_SERVICE_IDS: frozenset[str] = frozenset(
    {"console", "console-api", "console_api", "api", "web", "ui", "frontend", "admin"}
)


def _dotenv() -> dict[str, str]:
    """The launch scripts source `.env` before binding; mirror that so the
    probe and the app agree on the port. Process env still wins."""
    values: dict[str, str] = {}
    env_file = repo_root() / ".env"
    if not env_file.is_file():
        return values
    try:
        lines = env_file.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip("'\"")
    return values


def service_port(service: Service) -> int:
    raw = os.environ.get(service.port_env) or _dotenv().get(service.port_env)
    try:
        return int(raw) if raw else service.default_port
    except ValueError:
        return service.default_port


def port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.35) -> bool:
    """A plain TCP connect — no process table, no `ps`, no `lsof`.

    Cheap, and it survives the locked-down port CLAUDE.md hard rule #4 asks
    for. It also answers the question that actually matters: is something
    serving on that port, whoever started it.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def service_status(service: Service) -> dict[str, Any]:
    return {
        "id": service.id,
        "label": service.label,
        "port": service_port(service),
        "up": port_open(service_port(service)),
        "command": service.command,
    }


def process_control_enabled() -> bool:
    return os.environ.get(PROCESS_CONTROL_ENV, "on").strip().lower() not in {
        "off",
        "0",
        "false",
        "no",
    }


def _pid_dir() -> Path:
    # Same convention as deploy/production/start-apps.sh — `logs/` is
    # gitignored, so a PID file can never become a commit.
    return repo_root() / "logs"


def _pid_file(service: Service) -> Path:
    return _pid_dir() / f"{service.id}.pid"


def _log_file(service: Service) -> Path:
    return _pid_dir() / f"{service.id}.log"


def owned_pid(service: Service) -> int | None:
    """The PID of a process *this console started*, if it is still alive.

    A PID file, not a process scan: we only ever claim to control what we
    launched. Anything else on the port was started by a human in a terminal
    and is theirs to stop.
    """
    path = _pid_file(service)
    if not path.is_file():
        return None
    try:
        pid = int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    try:
        os.kill(pid, 0)
    except OSError:
        return None
    return pid


def _await_port(port: int, want_open: bool, timeout: float = 12.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if port_open(port) is want_open:
            return True
        time.sleep(0.25)
    return port_open(port) is want_open


def _result(service: Service, action: str, ok: bool, detail: str) -> dict[str, Any]:
    return {
        "id": service.id,
        "action": action,
        "ok": ok,
        "detail": detail,
        "command": service.command,
    }


def start_service(service: Service) -> dict[str, Any]:
    port = service_port(service)
    if port_open(port):
        return _result(service, "start", True, f"Already up on port {port}.")

    if not process_control_enabled():
        return _result(
            service,
            "start",
            False,
            f"Process control is disabled on this host. Run `{service.command}` "
            f"in a terminal; it will listen on port {port}.",
        )

    script = (repo_root() / service.command).resolve()
    if not script.is_file():
        return _result(
            service, "start", False, f"Launch script {service.command} not found in this checkout."
        )

    _pid_dir().mkdir(parents=True, exist_ok=True)
    try:
        with open(_log_file(service), "ab") as log:
            proc = subprocess.Popen(  # noqa: S603 - fixed argv, shell=False
                [_bash(), str(script)],
                cwd=str(repo_root()),
                stdout=log,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
    except OSError as exc:
        return _result(
            service,
            "start",
            False,
            f"Could not spawn a process here ({exc}). Run `{service.command}` by hand.",
        )

    _pid_file(service).write_text(f"{proc.pid}\n", encoding="utf-8")

    # The Popen returning is not evidence of anything. The port is.
    if _await_port(port, want_open=True):
        return _result(service, "start", True, f"Started on port {port}.")
    return _result(
        service,
        "start",
        False,
        f"Launched (pid {proc.pid}) but nothing is listening on port {port} yet — "
        f"see logs/{service.id}.log. Run `{service.command}` in a terminal to see why.",
    )


def stop_service(service: Service) -> dict[str, Any]:
    port = service_port(service)
    pid = owned_pid(service)

    if pid is None:
        if not port_open(port):
            _pid_file(service).unlink(missing_ok=True)
            return _result(service, "stop", True, f"Already down; nothing on port {port}.")
        return _result(
            service,
            "stop",
            False,
            f"Something is serving port {port}, but the console did not start it "
            f"and holds no PID for it — so it cannot be stopped from here. Stop it "
            f"in the terminal running `{service.command}` (Ctrl-C).",
        )

    if not process_control_enabled():
        return _result(
            service, "stop", False, "Process control is disabled on this host."
        )

    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except OSError:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError as exc:
            return _result(service, "stop", False, f"Could not signal pid {pid}: {exc}")

    if _await_port(port, want_open=False, timeout=8.0):
        _pid_file(service).unlink(missing_ok=True)
        return _result(service, "stop", True, f"Stopped; port {port} is free.")
    return _result(
        service,
        "stop",
        False,
        f"Sent SIGTERM to pid {pid}, but port {port} is still accepting connections.",
    )


def restart_service(service: Service) -> dict[str, Any]:
    stopped = stop_service(service)
    if not stopped["ok"]:
        return _result(service, "restart", False, stopped["detail"])
    started = start_service(service)
    return _result(service, "restart", started["ok"], started["detail"])


ACTIONS = {"start": start_service, "stop": stop_service, "restart": restart_service}


# ---------------------------------------------------------------------------
# Demo state summary
# ---------------------------------------------------------------------------


def state_summary(targets: Sequence[Any]) -> dict[str, Any]:
    root = repo_root()

    out_dir = root / "s3_enhancement" / "out"
    staged = len([p for p in out_dir.iterdir() if p.is_dir()]) if out_dir.is_dir() else 0

    events = root / "data" / "ticket_events.jsonl"
    ticket_events = 0
    if events.is_file():
        try:
            lines = events.read_text(encoding="utf-8").splitlines()
            ticket_events = sum(1 for line in lines if line.strip())
        except OSError:
            ticket_events = 0

    llm_cache = Path(os.environ.get("LLM_CACHE_DIR", root / ".cache" / "llm"))
    llm_entries = len(list(llm_cache.glob("*.json"))) if llm_cache.is_dir() else 0

    generated: list[str] = []
    for target in targets:
        for rel_path in getattr(target, "testgen_allowlist", ()):
            if (root / rel_path).is_file():
                generated.append(rel_path)

    return {
        "staged_proposals": staged,
        "ticket_events": ticket_events,
        "llm_cache_entries": llm_entries,
        "generated_test_files": sorted(dict.fromkeys(generated)),
    }


def target_summaries(targets: Sequence[Any], discovered_ids: Iterable[str]) -> list[dict[str, Any]]:
    discovered = set(discovered_ids)
    cache_dir = repo_root() / "s3_enhancement" / "cache"
    rows: list[dict[str, Any]] = []
    for target in targets:
        root_path = getattr(target, "root", None)
        story_path = getattr(target, "story_template_path", None)
        # A recording exists once the codegen beat has been replayed/recorded
        # for this namespace — the difference between a deterministic beat and
        # a live call on stage.
        try:
            recording = cache_dir / f"{target.stream_cache_key('codegen')}.json"
            has_recording = recording.is_file()
        except Exception:  # pragma: no cover - defensive, keys are literals
            has_recording = False
        rows.append(
            {
                "target_id": target.target_id,
                "display_name": target.display_name,
                "repo": _rel(root_path) if root_path else "",
                "story": _rel(story_path) if story_path else None,
                "discovered": target.target_id in discovered,
                "has_recording": has_recording,
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Repo onboarding
# ---------------------------------------------------------------------------

# A repo name becomes a directory under repos/ and is folded into every
# relevance embedding (relevance._document scores `f"{rel_path} {content}"`),
# so it has to be one plain path segment. Anything with a separator, a dot
# segment or a drive letter is refused rather than normalised — normalising a
# traversal attempt into something "safe" hides that it was attempted.
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class OnboardError(ValueError):
    """Onboarding input that cannot become a manifest."""


def validate_repo_name(name: str) -> str:
    candidate = (name or "").strip()
    if not candidate:
        raise OnboardError("name is required")
    if "/" in candidate or "\\" in candidate:
        raise OnboardError(f"name {candidate!r} must be a single path segment (no '/' or '\\')")
    if candidate in {".", ".."} or candidate.startswith("."):
        raise OnboardError(f"name {candidate!r} must not be a dot path")
    if Path(candidate).is_absolute() or ":" in candidate:
        raise OnboardError(f"name {candidate!r} must be a relative single path segment")
    if not _SAFE_NAME.match(candidate):
        raise OnboardError(
            f"name {candidate!r} must contain only letters, digits, '.', '_' and '-'"
        )
    return candidate


def build_manifest(payload: dict[str, Any]) -> dict[str, Any]:
    """The `.s3targets.json` body for one dropped repo.

    Only the keys `discovery._build_target` reads — writing anything else
    would invite a manifest that looks configured but isn't.
    """
    entry = {
        "target_id": payload.get("target_id"),
        "display_name": payload.get("display_name") or payload.get("target_id"),
        "cache_namespace": payload.get("cache_namespace"),
        "story": payload.get("story"),
        "core_files": list(payload.get("core_files") or []),
        "codegen_allowlist": list(payload.get("codegen_allowlist") or []),
        "testgen_allowlist": list(payload.get("testgen_allowlist") or []),
        "regression_paths": list(payload.get("regression_paths") or []),
        "post_apply_command": list(payload.get("post_apply_command") or []),
    }
    if payload.get("application_id"):
        entry["application_id"] = payload["application_id"]
    if payload.get("language"):
        entry["language"] = payload["language"]
    if payload.get("never_extra"):
        entry["never_extra"] = list(payload["never_extra"])
    if payload.get("harness_expected_files"):
        entry["harness_expected_files"] = list(payload["harness_expected_files"])
    return {"targets": [entry]}


def onboarding_warnings(
    name: str, repo_dir: Path, entry: dict[str, Any], written: bool
) -> list[str]:
    warnings: list[str] = []
    if not repo_dir.is_dir():
        warnings.append(
            f"repos/{name} does not exist yet — drop the source in before running a user story"
        )
    if not entry.get("regression_paths"):
        warnings.append(
            "No regression_paths declared — this target has no independent check that a "
            "user story broke nothing. Add a human-authored suite under tests/ (never inside the "
            "repo root, and never in a codegen or testgen allowlist)."
        )
    warnings.append(
        "No committed replay recording exists for this target yet, so its first codegen "
        "run is a live LLM call that records itself."
    )
    if written:
        warnings.append(
            "Targets register at import, so this manifest takes effect only after the "
            "console process is restarted. It is not live yet."
        )
    else:
        warnings.append(
            "dry_run — nothing was written. Re-send with dry_run:false to write the "
            "manifest, then restart the console for it to register."
        )
    return warnings
