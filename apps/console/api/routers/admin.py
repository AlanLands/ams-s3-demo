"""Manager-only admin panel: demo-state resets, target-app process control,
log housekeeping and repo onboarding.

Everything here was terminal-only until now, and switching to a terminal
mid-demo is exactly the seam a presentation should not have. The cost of
putting it behind HTTP is that a *button* can now do what previously took a
deliberate shell command — so the gate matters more than the convenience:

* `GET /admin/status` computes `reset_safe` from the real working tree and
  names the reason when it is false.
* `GET /admin/reset/{scope}/preview` lists the exact files a scope restores
  or deletes and which of them are currently dirty. The UI shows this before
  the button is usable.
* A source-restoring scope 409s while those files are dirty. Delete-only
  scopes (tickets/logs/proposals/caches) touch nothing but regenerable state
  and stay allowed.

The policy lives in `s3_enhancement/admin_ops.py`; this module is the HTTP
skin over it — role check, request shape, status codes.

Role: manager only. `require_identity` (the same dependency every `/s3`
route uses) establishes *who*; the role check below is the *what*, and it is
server-side for the same reason `scm.commit_blockers` and the release
record's approvals are — a client that could assert its own role could reset
another presenter's rehearsal out from under them.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from apps.console.api.auth import require_manager
from common.roster import Identity
from s3_enhancement import admin_ops, discovery, targets

router = APIRouter(prefix="/admin", tags=["admin"])




# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


@router.get("/status")
def status(identity: Identity = Depends(require_manager)) -> dict:
    """One read of everything the panel gates on: branch, tree cleanliness,
    which services answer on their port, which targets are registered, and
    how much generated state is lying around."""
    try:
        branch = admin_ops.current_branch()
        default_branch = admin_ops.default_branch_name()
        dirty_count = admin_ops.dirty_file_count()
        reset_safe, reason = admin_ops.reset_safety()
    except admin_ops.GitUnavailable as exc:
        # Not a 500: the panel is still useful without git, and the honest
        # answer to "is a reset safe" with no git is "no, and here's why".
        branch = "unknown"
        default_branch = "main"
        dirty_count = 0
        reset_safe = False
        reason = (
            f"git is unavailable here ({exc}) — a source reset cannot be "
            f"checked for safety, so it is refused."
        )

    registered = targets.all_targets()
    return {
        "branch": branch,
        "is_default_branch": branch == default_branch,
        "dirty_file_count": dirty_count,
        "reset_safe": reset_safe,
        "reset_blocked_reason": reason,
        "services": [admin_ops.service_status(s) for s in admin_ops.SERVICES],
        "targets": admin_ops.target_summaries(registered, targets.DISCOVERED_TARGET_IDS),
        "state": admin_ops.state_summary(registered),
    }


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------


class ResetRequest(BaseModel):
    scope: str
    confirm: bool = False


def _known_scope(scope: str) -> str:
    if scope not in admin_ops.SCOPES:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown reset scope {scope!r}. Known scopes: "
            + ", ".join(sorted(admin_ops.SCOPES)),
        )
    return scope


@router.get("/reset/{scope}/preview")
def reset_preview(scope: str, identity: Identity = Depends(require_manager)) -> dict:
    """Exactly what this scope would restore or delete, and which of those
    files currently carry uncommitted changes."""
    _known_scope(scope)
    try:
        return admin_ops.scope_preview(scope)
    except admin_ops.GitUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"git is unavailable: {exc}") from exc


@router.post("/reset")
def reset(payload: ResetRequest, identity: Identity = Depends(require_manager)) -> dict:
    """Run one reset scope.

    There is deliberately no "everything" scope: each reset is an explicit
    act, and a single button that did all of them would be the one nobody
    reads the confirmation on.
    """
    scope = _known_scope(payload.scope)
    if not payload.confirm:
        raise HTTPException(
            status_code=400,
            detail="confirm must be true — a reset is destructive and is never implicit.",
        )

    try:
        blockers = admin_ops.scope_blockers(scope)
    except admin_ops.GitUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"git is unavailable: {exc}") from exc

    if blockers:
        # 409, not 403: the request is legitimate, the tree state is what
        # conflicts. The reason names the files so the operator can commit or
        # stash them deliberately, in a terminal, where they can see what
        # they are giving up.
        raise HTTPException(status_code=409, detail=" ".join(blockers))

    try:
        return admin_ops.run_reset(scope)
    except admin_ops.ResetFailed as exc:
        detail = str(exc)
        if exc.output:
            detail = f"{detail}\n{exc.output}"
        raise HTTPException(status_code=500, detail=detail) from exc


# ---------------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------------


@router.post("/services/{service_id}/{action}")
def service_action(
    service_id: str, action: str, identity: Identity = Depends(require_manager)
) -> dict:
    """Start/stop/restart a target app, then re-probe the port and report what
    is actually true.

    The console itself has no service id. It cannot restart the process
    serving this request, so naming it is a 400 rather than an attempt that
    would drop the connection carrying the answer.
    """
    if service_id in admin_ops.CONSOLE_SERVICE_IDS:
        raise HTTPException(
            status_code=400,
            detail="The console cannot control the process serving this request. "
            "Restart it from the terminal running apps/run-console.sh.",
        )
    service = admin_ops.SERVICES_BY_ID.get(service_id)
    if service is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown service {service_id!r}. Known services: "
            + ", ".join(s.id for s in admin_ops.SERVICES),
        )
    handler = admin_ops.ACTIONS.get(action)
    if handler is None:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown action {action!r}. Expected start, stop or restart.",
        )
    return handler(service)


# ---------------------------------------------------------------------------
# Repo onboarding
# ---------------------------------------------------------------------------


class OnboardRequest(BaseModel):
    name: str
    display_name: str = ""
    target_id: str = ""
    cache_namespace: str = ""
    story: str | None = None
    application_id: str = ""
    language: str = ""
    core_files: list[str] = Field(default_factory=list)
    codegen_allowlist: list[str] = Field(default_factory=list)
    testgen_allowlist: list[str] = Field(default_factory=list)
    never_extra: list[str] = Field(default_factory=list)
    harness_expected_files: list[str] = Field(default_factory=list)
    regression_paths: list[str] = Field(default_factory=list)
    post_apply_command: list[str] = Field(default_factory=list)
    dry_run: bool = True


@router.post("/repos/onboard")
def onboard_repo(payload: OnboardRequest, identity: Identity = Depends(require_manager)) -> dict:
    """Validate (and optionally write) a `repos/<name>/.s3targets.json`.

    Validation runs the candidate entry through
    `s3_enhancement.discovery._build_target` — the same code path import-time
    registration uses — rather than restating its rules here. Two
    implementations of "is this manifest valid" would drift, and the one that
    drifts is always the copy.
    """
    errors: list[str] = []
    root = admin_ops.repo_root()

    try:
        name = admin_ops.validate_repo_name(payload.name)
    except admin_ops.OnboardError as exc:
        # Without a safe name there is no path to report, so this is terminal.
        return {
            "ok": False,
            "manifest_path": None,
            "manifest": None,
            "written": False,
            "warnings": [],
            "errors": [str(exc)],
        }

    repo_dir = root / "repos" / name
    manifest_path = repo_dir / admin_ops.MANIFEST_NAME
    manifest_rel = f"repos/{name}/{admin_ops.MANIFEST_NAME}"

    manifest = admin_ops.build_manifest(payload.model_dump())
    entry = manifest["targets"][0]

    # Collision check first, and against the live registry rather than the
    # manifest files on disk: cache_namespace *is* the committed recording's
    # filename, so two targets sharing one is a silent replay mix-up rather
    # than a loud failure. This is the check that makes that unrepresentable.
    for existing in targets.all_targets():
        if entry["target_id"] and existing.target_id == entry["target_id"]:
            errors.append(
                f"target_id {entry['target_id']!r} is already registered by "
                f"{existing.display_name!r}"
            )
        if entry["cache_namespace"] and existing.cache_namespace == entry["cache_namespace"]:
            errors.append(
                f"cache_namespace {entry['cache_namespace']!r} is already used by target "
                f"{existing.target_id!r} — the namespace is the replay recording's filename, "
                f"so sharing one silently crosses two targets' recordings"
            )

    # Then discovery's own rules — required keys, list-vs-string types, the
    # user story path existing, mutation shape.
    try:
        discovery._build_target(entry, repo_dir, manifest_path)
    except discovery.ManifestError as exc:
        errors.append(str(exc).replace(str(manifest_path), manifest_rel))
    except (KeyError, TypeError, ValueError) as exc:
        errors.append(f"{manifest_rel}: {exc}")

    if errors:
        return {
            "ok": False,
            "manifest_path": manifest_rel,
            "manifest": manifest,
            "written": False,
            "warnings": [],
            "errors": errors,
        }

    written = False
    if not payload.dry_run:
        if manifest_path.exists():
            return {
                "ok": False,
                "manifest_path": manifest_rel,
                "manifest": manifest,
                "written": False,
                "warnings": [],
                "errors": [
                    f"{manifest_rel} already exists — edit it directly rather than "
                    f"overwriting a registered target's manifest"
                ],
            }
        try:
            repo_dir.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            written = True
        except OSError as exc:
            return {
                "ok": False,
                "manifest_path": manifest_rel,
                "manifest": manifest,
                "written": False,
                "warnings": [],
                "errors": [f"could not write {manifest_rel}: {exc}"],
            }

    return {
        "ok": True,
        "manifest_path": manifest_rel,
        "manifest": manifest,
        "written": written,
        "warnings": admin_ops.onboarding_warnings(name, repo_dir, entry, written),
        "errors": [],
    }


# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------


@router.get("/logs")
def logs(identity: Identity = Depends(require_manager)) -> dict:
    return {"files": admin_ops.log_files()}


@router.delete("/logs")
def clear_logs(identity: Identity = Depends(require_manager)) -> dict[str, Any]:
    return admin_ops.delete_log_files()
