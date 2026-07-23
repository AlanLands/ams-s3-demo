"""S3 REST endpoints -- thin wrappers over s3_enhancement's existing
Enhancement Delivery modules. No business logic lives here; every function
called below is the exact same one the Streamlit view (`s3_enhancement/app.py`)
already called.
"""

from __future__ import annotations

import json
import subprocess
import sys

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import require_identity
from common.constants import AI_SUGGESTION_LABEL
from common.gitlab_client import GitLabError, get_client
from common.llm import LLMError
from s1_triage.roster_auth import Identity
from s3_enhancement.analyze import draft_effort_estimate, draft_impact_analysis
from s3_enhancement.codegen import generate_change
from s3_enhancement.cr import render_cr, sanitize_tier_name
from s3_enhancement.docgen import draft_release_notes
from s3_enhancement.harness import latest_harness_run
from s3_enhancement.relevance import (
    discover_gitlab_files,
    discover_mockapp_files,
    select_relevant_files,
)
from s3_enhancement.repo_match import suggest_target_repo
from s3_enhancement.testgen import generate_tests

router = APIRouter(prefix="/s3", tags=["s3"])


class TierRequest(BaseModel):
    tier_name: str


def _cr_text_or_400(tier_name: str) -> str:
    clean, error = sanitize_tier_name(tier_name)
    if error:
        raise HTTPException(status_code=422, detail=error)
    assert clean is not None
    return render_cr(clean)


def _run_pytest() -> str:
    process = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_s3_coverage_upgrade.py", "-v"],
        check=False,
        capture_output=True,
        text=True,
    )
    return process.stdout + process.stderr


def _selection_dict(selection) -> dict:
    screen = selection.subsystem_screen
    return {
        "candidate_pool_size": selection.candidate_pool_size,
        "candidate_pool_by_language": selection.candidate_pool_by_language,
        "selected_files": list(selection.selected.keys()),
        "subsystem_screen": {
            "in_scope": list(screen.in_scope),
            "screened_out": list(screen.screened_out),
            "scores": screen.scores,
        },
    }


@router.get("/cr")
def cr(tier_name: str = "Elite", identity: Identity = Depends(require_identity)) -> dict:
    clean, error = sanitize_tier_name(tier_name)
    if error:
        raise HTTPException(status_code=422, detail=error)
    assert clean is not None
    return {"tier_name": clean, "cr_text": render_cr(clean)}


@router.post("/analyze")
def analyze(payload: TierRequest, identity: Identity = Depends(require_identity)) -> dict:
    cr_text = _cr_text_or_400(payload.tier_name)
    try:
        impact_text = draft_impact_analysis(cr_text)
        effort = draft_effort_estimate(cr_text)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    selection = select_relevant_files(cr_text, discover_mockapp_files())
    return {
        "label": AI_SUGGESTION_LABEL,
        "impact_analysis": impact_text,
        "effort_estimate": {
            "hours_class": effort.hours_class,
            "priority_equivalent": effort.priority_equivalent,
            "reasoning": effort.reasoning,
        },
        "file_selection": _selection_dict(selection),
    }


@router.post("/generate")
def generate(payload: TierRequest, identity: Identity = Depends(require_identity)) -> dict:
    cr_text = _cr_text_or_400(payload.tier_name)
    try:
        result = generate_change(payload.tier_name, cr_text)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    selection = select_relevant_files(cr_text, discover_mockapp_files())
    return {
        "label": AI_SUGGESTION_LABEL,
        "tier_name": result.tier_name,
        "diff_text": result.diff_text,
        "files_changed": result.files_changed,
        "used_replay": result.used_replay,
        "file_selection": _selection_dict(selection),
        "token_panel": {
            "scoped_input_tokens": result.scoped_input_tokens,
            "scoped_output_tokens": result.scoped_output_tokens,
            "naive_input_tokens_estimate": result.naive_input_tokens_estimate,
        },
    }


@router.post("/tests")
def tests(payload: TierRequest, identity: Identity = Depends(require_identity)) -> dict:
    cr_text = _cr_text_or_400(payload.tier_name)
    try:
        result = generate_tests(payload.tier_name, cr_text)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    pytest_output = _run_pytest()
    return {
        "label": AI_SUGGESTION_LABEL,
        "diff_text": result.diff_text,
        "files_changed": result.files_changed,
        "used_replay": result.used_replay,
        "pytest_output": pytest_output,
        "token_panel": {
            "scoped_input_tokens": result.scoped_input_tokens,
            "scoped_output_tokens": result.scoped_output_tokens,
        },
    }


@router.post("/release-notes")
def release_notes(payload: TierRequest, identity: Identity = Depends(require_identity)) -> dict:
    cr_text = _cr_text_or_400(payload.tier_name)
    try:
        text = draft_release_notes(cr_text)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"label": AI_SUGGESTION_LABEL, "release_notes": text}


@router.get("/harness/latest")
def harness_latest(identity: Identity = Depends(require_identity)) -> dict:
    run_dir = latest_harness_run()
    if run_dir is None or not (run_dir / "status.json").exists():
        raise HTTPException(
            status_code=404,
            detail="No harness run found yet — run demo/run_s3_harness.sh first.",
        )

    status_dict = json.loads((run_dir / "status.json").read_text(encoding="utf-8"))
    diff_path = run_dir / "diff.patch"
    diff_text = diff_path.read_text(encoding="utf-8") if diff_path.exists() else ""
    return {"label": AI_SUGGESTION_LABEL, "status": status_dict, "diff_text": diff_text}


@router.get("/gitlab/projects")
def gitlab_projects(identity: Identity = Depends(require_identity)) -> list:
    try:
        return get_client().list_projects()
    except GitLabError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/gitlab/projects/{project_id}/scope")
def gitlab_scope(
    project_id: str,
    payload: TierRequest,
    identity: Identity = Depends(require_identity),
) -> dict:
    cr_text = _cr_text_or_400(payload.tier_name)
    try:
        repo_size = len(get_client().list_repo_paths(project_id))
        gitlab_files = discover_gitlab_files(project_id, cr_text)
        selection = select_relevant_files(cr_text, gitlab_files, core_files=(), design_docs={})
    except GitLabError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {
        "repo_size": repo_size,
        "files_reached_llm": len(selection.selected),
        "selected_files": list(selection.selected.keys()),
    }


@router.post("/gitlab/scope-auto")
def gitlab_scope_auto(
    payload: TierRequest, identity: Identity = Depends(require_identity)
) -> dict:
    """Same as /gitlab/projects/{id}/scope, but for when the caller doesn't know
    which repo the CR belongs to — an AI pick over the project list stands in for
    the manual project_id above, labeled like every other AI suggestion."""
    cr_text = _cr_text_or_400(payload.tier_name)
    try:
        projects = get_client().list_projects()
        suggestion = suggest_target_repo(cr_text, projects)
        project_id = suggestion.best_match.project_id
        repo_size = len(get_client().list_repo_paths(project_id))
        gitlab_files = discover_gitlab_files(project_id, cr_text)
        selection = select_relevant_files(cr_text, gitlab_files, core_files=(), design_docs={})
    except GitLabError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    projects_by_id = {str(project.get("id")): project for project in projects}

    def _describe(match) -> dict:
        project = projects_by_id.get(match.project_id, {})
        return {
            "id": match.project_id,
            "name": project.get("name_with_namespace") or project.get("name"),
            "reasoning": match.reasoning,
        }

    suggested_project = {
        **_describe(suggestion.best_match),
        "confidence": suggestion.best_match.confidence,
    }
    return {
        "label": AI_SUGGESTION_LABEL,
        "suggested_project": suggested_project,
        "alternates": [_describe(alt) for alt in suggestion.alternates],
        "repo_size": repo_size,
        "files_reached_llm": len(selection.selected),
        "selected_files": list(selection.selected.keys()),
    }
