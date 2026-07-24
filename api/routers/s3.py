"""S3 REST endpoints -- thin wrappers over s3_enhancement's existing
Enhancement Delivery modules. No business logic lives here; every function
called below is the exact same one the Streamlit view (`s3_enhancement/app.py`)
already called.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import require_identity, require_session_id
from api.session import get_session_data
from common.constants import AI_SUGGESTION_LABEL
from common.gitlab_client import GitLabError, get_client
from common.jira_client import JiraError, get_jira_client
from common.llm import LLMError
from common.ticket_events import (
    distinct_tickets_with_action,
    events_for,
    events_log_marker,
    record_event,
)
from s1_triage.roster_auth import Identity
from s3_enhancement import targets, testrun
from s3_enhancement.analyze import (
    draft_adhoc_effort_estimate,
    draft_adhoc_impact_analysis,
    draft_cross_team_impact,
    draft_effort_estimate,
    draft_impact_analysis,
)
from s3_enhancement.codegen import (
    add_file_to_proposal,
    apply_change,
    propose_change,
    revise_change,
)
from s3_enhancement.cr import render_cr, sanitize_tier_name
from s3_enhancement.docgen import draft_design_doc, draft_release_notes
from s3_enhancement.harness import latest_harness_run
from s3_enhancement.quick_chat import QuickChatTurn, continue_session
from s3_enhancement.relevance import (
    discover_files_for_target,
    discover_gitlab_files,
    estimate_tokens,
    select_relevant_files,
)
from s3_enhancement.repo_match import suggest_target_repo
from s3_enhancement.screenshots import ScreenshotError, capture_form_screenshot
from s3_enhancement.targets import Target
from s3_enhancement.testgen import generate_tests

_QUICK_CHAT_SESSION_KEY = "s3_quick_chat_history"

router = APIRouter(prefix="/s3", tags=["s3"])


class TierRequest(BaseModel):
    tier_name: str
    target_id: str | None = None
    # Optional Jira ticket key this action should be logged against (e.g.
    # "AMS-101") — purely for the Activity feed; the pipeline behaves
    # identically whether or not it's supplied.
    ticket_number: str | None = None


class AdhocAnalyzeRequest(BaseModel):
    # Free-text ticket content — unlike TierRequest, there's no tier_name/
    # target_id because this is for a ticket with no CR/target registered in
    # this console (e.g. a cross-team ticket raised against another app).
    cr_text: str
    ticket_number: str | None = None


def _cr_text_or_400(tier_name: str, *, target: Target | None = None) -> str:
    clean, error = sanitize_tier_name(tier_name)
    if error:
        raise HTTPException(status_code=422, detail=error)
    assert clean is not None
    return render_cr(clean, target=target)


def _run_suite_or_502(target: Target) -> testrun.SuiteRun:
    """Run the target's generated test suite with the target's own runner —
    pytest by default; a Java target declares its Maven invocation on the
    Target itself (test_command/test_cwd). A missing runner binary surfaces as
    a clean 502, not an uncaught FileNotFoundError 500."""
    try:
        return testrun.run_suite(target)
    except testrun.TestRunnerNotFoundError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


def _suite_run_dict(run: testrun.SuiteRun) -> dict:
    return {
        "passed": run.passed,
        "returncode": run.returncode,
        "output": run.output,
        "duration_s": run.duration_s,
        "summary": run.summary(),
        "cases": [
            {
                "name": case.name,
                "classname": case.classname,
                "description": case.description,
                "status": case.status,
                "time_s": case.time_s,
                "message": case.message,
            }
            for case in run.cases
        ],
    }


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


def _token_panel(usage: dict, all_files: dict[str, str]) -> dict:
    """Same scoped-vs-naive comparison /s3/generate already shows, for any
    other beat that also reads codebase context through the relevance
    funnel (impact analysis, cross-team impact) — `all_files` is whatever
    that beat's own `discover_files_for_target()` call already produced."""
    return {
        "scoped_input_tokens": usage.get("input_tokens"),
        "scoped_output_tokens": usage.get("output_tokens"),
        "estimated": bool(usage.get("estimated")),
        "naive_input_tokens_estimate": sum(
            estimate_tokens(content) for content in all_files.values()
        ),
    }


@router.get("/reset-marker")
def reset_marker(identity: Identity = Depends(require_identity)) -> dict:
    """Changes whenever the ticket-events log is cleared (e.g. demo/reset_s3.sh
    between rehearsals). The frontend compares this against what it last saw
    to know its localStorage-cached per-ticket analysis/proposal state is
    stale and should be dropped, instead of showing results for a ticket the
    server no longer has any record of."""
    return {"marker": events_log_marker()}


@router.get("/cr")
def cr(
    tier_name: str = "Elite",
    target_id: str | None = None,
    identity: Identity = Depends(require_identity),
) -> dict:
    clean, error = sanitize_tier_name(tier_name)
    if error:
        raise HTTPException(status_code=422, detail=error)
    assert clean is not None
    target = targets.get_target(target_id)
    return {"tier_name": clean, "cr_text": render_cr(clean, target=target)}


@router.post("/analyze")
def analyze(payload: TierRequest, identity: Identity = Depends(require_identity)) -> dict:
    target = targets.get_target(payload.target_id)
    cr_text = _cr_text_or_400(payload.tier_name, target=target)
    usage: dict = {}
    try:
        impact_text = draft_impact_analysis(cr_text, target=target, usage_out=usage)
        effort = draft_effort_estimate(cr_text, target=target)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    all_files = discover_files_for_target(target, cr_text)
    selection = select_relevant_files(cr_text, all_files, core_files=target.core_files)
    if payload.ticket_number:
        record_event(
            payload.ticket_number,
            "ai",
            "impact_analysis_drafted",
            detail=f"{effort.hours_class} / {effort.priority_equivalent}",
        )
    return {
        "label": AI_SUGGESTION_LABEL,
        "impact_analysis": impact_text,
        "effort_estimate": {
            "hours_class": effort.hours_class,
            "priority_equivalent": effort.priority_equivalent,
            "reasoning": effort.reasoning,
        },
        "file_selection": _selection_dict(selection),
        "token_panel": _token_panel(usage, all_files),
    }


@router.post("/analyze-adhoc")
def analyze_adhoc(
    payload: AdhocAnalyzeRequest, identity: Identity = Depends(require_identity)
) -> dict:
    """Impact analysis for a ticket with no linked CR/target in this console
    (e.g. a cross-team ticket for another application) — runs directly off
    the ticket's own text instead of one of the two pinned CR templates, so
    there's no codebase/file_selection to report."""
    cr_text = payload.cr_text.strip()
    if not cr_text:
        raise HTTPException(status_code=422, detail="cr_text must not be empty")
    if len(cr_text) > 4000:
        raise HTTPException(status_code=422, detail="cr_text is too long (max 4000 characters)")
    try:
        impact_text = draft_adhoc_impact_analysis(cr_text)
        effort = draft_adhoc_effort_estimate(cr_text)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if payload.ticket_number:
        record_event(
            payload.ticket_number,
            "ai",
            "impact_analysis_drafted",
            detail=f"{effort.hours_class} / {effort.priority_equivalent}",
        )
    return {
        "label": AI_SUGGESTION_LABEL,
        "impact_analysis": impact_text,
        "effort_estimate": {
            "hours_class": effort.hours_class,
            "priority_equivalent": effort.priority_equivalent,
            "reasoning": effort.reasoning,
        },
    }


@router.post("/impact/cross-team")
def cross_team_impact(payload: TierRequest, identity: Identity = Depends(require_identity)) -> dict:
    """AI-suggested list of other application teams this CR would also
    require work from — a human confirms each one via /jira/cross-team-ticket
    before any ticket is actually created."""
    target = targets.get_target(payload.target_id)
    cr_text = _cr_text_or_400(payload.tier_name, target=target)
    usage: dict = {}
    try:
        impacts = draft_cross_team_impact(cr_text, target=target, usage_out=usage)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    all_files = discover_files_for_target(target, cr_text)
    if payload.ticket_number:
        record_event(
            payload.ticket_number,
            "ai",
            "cross_team_impact_checked",
            detail=", ".join(impact.app_name for impact in impacts) or "none found",
        )
    return {
        "label": AI_SUGGESTION_LABEL,
        "impacts": [
            {
                "app_name": impact.app_name,
                "reason": impact.reason,
                "suggested_summary": impact.suggested_summary,
            }
            for impact in impacts
        ],
        "token_panel": _token_panel(usage, all_files),
    }


class CrossTeamTicketRequest(BaseModel):
    app_name: str
    summary: str
    description: str = ""
    primary_ticket_key: str
    assignee: str | None = None


@router.post("/jira/cross-team-ticket")
def create_cross_team_ticket(
    payload: CrossTeamTicketRequest, identity: Identity = Depends(require_identity)
) -> dict:
    """Human-confirmed creation of a linked Jira ticket for another affected
    team (see /impact/cross-team) — the only place this router ever writes
    a cross-team ticket to Jira."""
    project_key = os.environ.get("JIRA_PROJECT_KEY", "AMS")
    try:
        issue = get_jira_client().create_issue(
            project_key,
            payload.summary,
            payload.description,
            issue_type="Task",
            assignee_name=payload.assignee,
        )
    except JiraError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    new_key = str(issue.get("key", ""))
    record_event(
        new_key,
        "human",
        "cross_team_ticket_created",
        detail=f"linked_from={payload.primary_ticket_key}"
        + (f";assignee={payload.assignee}" if payload.assignee else ""),
    )
    record_event(payload.primary_ticket_key, "human", "cross_team_ticket_linked", detail=new_key)

    return {"label": AI_SUGGESTION_LABEL, "app_name": payload.app_name, "issue": issue}


class AssignTicketRequest(BaseModel):
    key: str
    assignee: str


@router.post("/jira/assign-ticket")
def assign_ticket(
    payload: AssignTicketRequest, identity: Identity = Depends(require_identity)
) -> dict:
    """Assign an already-created ticket — split from creation so a ticket can
    land as open/unassigned first and a manager can pick the assignee later,
    on their own schedule."""
    try:
        issue = get_jira_client().assign_issue(payload.key, payload.assignee)
    except JiraError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    record_event(payload.key, "human", "ticket_assigned", detail=payload.assignee)
    return {"label": AI_SUGGESTION_LABEL, "issue": issue}


class TicketStatusRequest(BaseModel):
    key: str
    status: str


@router.post("/jira/ticket-status")
def set_ticket_status(
    payload: TicketStatusRequest, identity: Identity = Depends(require_identity)
) -> dict:
    """Mark a ticket's status — e.g. the assigned team logs in, does their
    part, and marks their cross-team ticket Done so the original CR's
    engineer sees the dependency clear."""
    try:
        issue = get_jira_client().set_issue_status(payload.key, payload.status)
    except JiraError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    record_event(payload.key, "human", "ticket_status_changed", detail=payload.status)
    return {"label": AI_SUGGESTION_LABEL, "issue": issue}


@router.get("/jira/dependencies")
def jira_dependencies(
    primary_ticket_key: str, identity: Identity = Depends(require_identity)
) -> dict:
    """Cross-team tickets linked to a primary CR ticket, with their current
    status — derived from the append-only ticket-events log (not client
    state), so an engineer's screen can see a dependency clear even after
    another team, logged in separately, marks their ticket Done."""
    linked_keys = [
        event["detail"]
        for event in events_for(primary_ticket_key)
        if event.get("action") == "cross_team_ticket_linked"
    ]
    client = get_jira_client()
    dependencies = []
    for key in linked_keys:
        try:
            dependencies.append(client.get_issue(key))
        except JiraError:
            dependencies.append({"key": key, "status": None, "summary": None})
    return {"primary_ticket_key": primary_ticket_key, "dependencies": dependencies}


@router.get("/ticket-events")
def ticket_events(
    ticket_number: str, identity: Identity = Depends(require_identity)
) -> dict:
    """A ticket's real activity feed — every AI/human/system action recorded
    against it, oldest first. Backs the ticket modal's Activity tab."""
    return {"ticket_number": ticket_number, "events": events_for(ticket_number)}


class ReviseRequest(BaseModel):
    proposal_id: str
    instruction: str


class ApplyRequest(BaseModel):
    proposal_id: str
    # If set, apply only this one staged file (per-file "Apply" in the diff
    # view) instead of the whole proposal.
    file_path: str | None = None
    ticket_number: str | None = None


class AddFileRequest(BaseModel):
    proposal_id: str
    file_path: str
    instruction: str
    ticket_number: str | None = None


@router.post("/generate")
def generate(payload: TierRequest, identity: Identity = Depends(require_identity)) -> dict:
    """Propose (stage + diff) the target's file replacements.

    Does NOT write to the working tree — the diff is a review-gated
    suggestion, GitLab-Duo style. Call /s3/revise to ask for tweaks, and
    /s3/apply(proposal_id) once a human approves it, before anything lands
    on disk.
    """
    target = targets.get_target(payload.target_id)
    cr_text = _cr_text_or_400(payload.tier_name, target=target)
    try:
        result = propose_change(payload.tier_name, cr_text, target=target)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    all_files = discover_files_for_target(target, cr_text)
    selection = select_relevant_files(cr_text, all_files, core_files=target.core_files)
    if payload.ticket_number:
        record_event(
            payload.ticket_number,
            "ai",
            "code_change_proposed",
            detail=f"{len(result.files_changed)} file(s), proposal {result.proposal_id}",
        )
    return {
        "label": AI_SUGGESTION_LABEL,
        "tier_name": result.tier_name,
        "proposal_id": result.proposal_id,
        "diff_text": result.diff_text,
        "files_changed": result.files_changed,
        "file_reasons": result.file_reasons or {},
        "used_replay": result.used_replay,
        "file_selection": _selection_dict(selection),
        "token_panel": {
            "scoped_input_tokens": result.scoped_input_tokens,
            "scoped_output_tokens": result.scoped_output_tokens,
            "estimated": result.tokens_estimated,
            "naive_input_tokens_estimate": result.naive_input_tokens_estimate,
        },
    }


@router.post("/revise")
def revise(payload: ReviseRequest, identity: Identity = Depends(require_identity)) -> dict:
    """Ask the AI to tweak a not-yet-applied proposal (ChatGPT/GitLab-Duo-
    suggestion style) — still doesn't touch the working tree."""
    try:
        result = revise_change(payload.proposal_id, payload.instruction)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {
        "label": AI_SUGGESTION_LABEL,
        "proposal_id": result.proposal_id,
        "diff_text": result.diff_text,
        "files_changed": result.files_changed,
        "message": result.message,
        "token_panel": {
            "scoped_input_tokens": result.scoped_input_tokens,
            "scoped_output_tokens": result.scoped_output_tokens,
        },
    }


_POST_APPLY_OUTPUT_TAIL = 4000


def _run_post_apply(applied_files: list[str], ticket_number: str | None) -> dict:
    """Run every registered target's post-apply migration owed for this file
    set (see targets.post_apply_commands_for) — e.g. rebuilding the mockapp
    SQLite schema so a CR that adds a column doesn't crash the running
    portal. Subprocesses, not in-process imports, so each step runs against
    the newly written module files rather than whatever this API process
    imported at startup. This is target-registry-driven on purpose: any new
    CR against a registered root inherits its migration step automatically.

    Returns {"ok": bool, "steps": [...]} so a migration crash — the applied
    CR broke the app — reaches the caller with its traceback instead of
    dying silently in a discarded subprocess result.
    """
    repo_root = Path(__file__).resolve().parents[2]
    steps = []
    for command in targets.post_apply_commands_for(applied_files, repo_root):
        argv = [sys.executable if part == "{python}" else part for part in command]
        cmd_display = " ".join(command).replace("{python}", "python")
        result = subprocess.run(argv, check=False, capture_output=True, text=True)
        output_tail = ""
        if result.returncode != 0:
            output_tail = (result.stdout + result.stderr)[-_POST_APPLY_OUTPUT_TAIL:]
        steps.append(
            {
                "command": cmd_display,
                "returncode": result.returncode,
                "output_tail": output_tail,
            }
        )
        if ticket_number:
            if result.returncode == 0:
                record_event(
                    ticket_number,
                    "system",
                    "post_apply_migration",
                    detail=cmd_display,
                )
            else:
                last_line = output_tail.strip().splitlines()[-1] if output_tail.strip() else ""
                record_event(
                    ticket_number,
                    "system",
                    "post_apply_migration_failed",
                    detail=f"{cmd_display}: {last_line}",
                )
    return {"ok": all(step["returncode"] == 0 for step in steps), "steps": steps}


@router.post("/apply")
def apply(payload: ApplyRequest, identity: Identity = Depends(require_identity)) -> dict:
    """Apply a reviewed proposal to the working tree — the only endpoint that
    ever writes to the real repo files. Pass `file_path` to apply just one
    staged file instead of the whole proposal."""
    try:
        applied_files = apply_change(payload.proposal_id, payload.file_path)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    post_apply = _run_post_apply(applied_files, payload.ticket_number)

    if payload.ticket_number:
        record_event(
            payload.ticket_number,
            "human",
            "code_change_applied",
            detail=payload.file_path or payload.proposal_id,
        )
    return {
        "proposal_id": payload.proposal_id,
        "applied_files": applied_files,
        "post_apply": post_apply,
    }


@router.post("/add-file")
def add_file(payload: AddFileRequest, identity: Identity = Depends(require_identity)) -> dict:
    """Add one more file to an in-review proposal that the AI's original file
    selection didn't cover, with an instruction for what change it needs —
    for when the developer reviewing the diff realizes another file also
    needs to change. Same review-gated diff/apply loop as any other file;
    nothing is written to the real repo until /s3/apply."""
    try:
        result = add_file_to_proposal(payload.proposal_id, payload.file_path, payload.instruction)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if payload.ticket_number:
        record_event(
            payload.ticket_number,
            "human",
            "proposal_file_added",
            detail=payload.file_path,
        )
    return {
        "label": AI_SUGGESTION_LABEL,
        "proposal_id": result.proposal_id,
        "diff_text": result.diff_text,
        "files_changed": result.files_changed,
        "message": result.message,
        "token_panel": {
            "scoped_input_tokens": result.scoped_input_tokens,
            "scoped_output_tokens": result.scoped_output_tokens,
        },
    }


@router.get("/screenshots/{stage}")
def screenshot(
    stage: Literal["before", "after"],
    namespace: str = targets.MOCKAPP_ENDORSEMENT_FIELD_ADD.cache_namespace,
    identity: Identity = Depends(require_identity),
) -> dict:
    """Base64-encoded before/after PNG for the endorsement-form demo beat
    (see s3_enhancement/screenshots.py). 404s if that stage hasn't been
    captured yet — run demo/warm_s3_cache.sh or capture live with
    SCREENSHOT_MODE=record."""
    try:
        png_bytes = capture_form_screenshot(stage, namespace=namespace)
    except ScreenshotError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {
        "stage": stage,
        "namespace": namespace,
        "image_base64": base64.b64encode(png_bytes).decode("ascii"),
    }


@router.get("/jira/board")
def jira_board(identity: Identity = Depends(require_identity)) -> dict:
    """Compact issue list driving the engineer's Jira-styled board view.

    The seeded/recorded search result only ever reflects the fixed demo
    tickets (AMS-101/102/098) — it has no way to know about a cross-team
    ticket created moments ago. Those are tracked instead via the
    ticket-events log (every creation records a `cross_team_ticket_created`
    event on the new key), so this merges that list in — this is how an
    assignee logging in separately actually sees their new ticket on the
    shared board, not just via the dependency lookup.
    """
    project_key = os.environ.get("JIRA_PROJECT_KEY", "AMS")
    client = get_jira_client()
    try:
        issues = client.search_issues(f"project = {project_key} ORDER BY updated DESC")
    except JiraError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    seen_keys = {issue.get("key") for issue in issues}
    created_keys = distinct_tickets_with_action("cross_team_ticket_created")
    for key in sorted(created_keys - seen_keys):
        try:
            issues.append(client.get_issue(key))
        except JiraError:
            continue

    # Overlay each issue's current status/assignee from the per-issue cache:
    # the seeded search recording is static, but assign/status changes made
    # during a session (analysis started -> In Progress, QA handoff) update
    # the get_issue cache — without this merge the board would show stale
    # columns after any workflow transition.
    merged = []
    for issue in issues:
        key = issue.get("key")
        try:
            fresh = client.get_issue(str(key))
        except JiraError:
            merged.append(issue)
            continue
        merged.append({**issue, **{k: v for k, v in fresh.items() if v is not None}})

    return {"project_key": project_key, "issues": merged}


@router.post("/tests/generate")
def tests_generate(payload: TierRequest, identity: Identity = Depends(require_identity)) -> dict:
    """Generate (and stage into the working tree) the target's test file only
    — nothing runs yet. The tester reviews the diff, then hits /tests/run."""
    target = targets.get_target(payload.target_id)
    cr_text = _cr_text_or_400(payload.tier_name, target=target)
    try:
        result = generate_tests(payload.tier_name, cr_text, target=target)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if payload.ticket_number:
        record_event(
            payload.ticket_number,
            "ai",
            "tests_generated",
            detail=", ".join(result.files_changed),
        )
    return {
        "label": AI_SUGGESTION_LABEL,
        "diff_text": result.diff_text,
        "files_changed": result.files_changed,
        "used_replay": result.used_replay,
        "token_panel": {
            "scoped_input_tokens": result.scoped_input_tokens,
            "scoped_output_tokens": result.scoped_output_tokens,
            "estimated": result.tokens_estimated,
        },
    }


@router.post("/tests/run")
def tests_run(payload: TierRequest, identity: Identity = Depends(require_identity)) -> dict:
    """Run the previously generated suite and return parsed per-test results."""
    target = targets.get_target(payload.target_id)
    if not testrun.generated_test_file_exists(target):
        raise HTTPException(
            status_code=409,
            detail="No generated test file to run yet — generate the tests first.",
        )
    run = _run_suite_or_502(target)
    if payload.ticket_number:
        summary = run.summary()
        record_event(
            payload.ticket_number,
            "ai",
            "tests_passed" if run.passed else "tests_failed",
            detail=f"{summary['passed']}/{summary['total']} passed",
        )
    return {"label": AI_SUGGESTION_LABEL, **_suite_run_dict(run)}


@router.post("/tests/mutation")
def tests_mutation(payload: TierRequest, identity: Identity = Depends(require_identity)) -> dict:
    """The "prove the tests catch bugs" beat: inject the target's seeded bug,
    re-run the generated suite, and always revert the working tree — a strong
    suite goes red on exactly the right test, then the bug disappears."""
    target = targets.get_target(payload.target_id)
    try:
        result = testrun.run_mutation(target)
    except testrun.MutationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except testrun.TestRunnerNotFoundError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if payload.ticket_number:
        record_event(
            payload.ticket_number,
            "ai",
            "mutation_check",
            detail=(
                "seeded bug caught by the suite"
                if result.tests_caught_bug
                else "seeded bug NOT caught by the suite"
            ),
        )
    return {
        "label": AI_SUGGESTION_LABEL,
        "description": result.description,
        "file": result.rel_path,
        "mutation_diff": result.mutation_diff,
        "tests_caught_bug": result.tests_caught_bug,
        "reverted": True,
        **_suite_run_dict(result.run),
    }


@router.post("/tests")
def tests(payload: TierRequest, identity: Identity = Depends(require_identity)) -> dict:
    """Legacy one-shot generate-and-run — kept for compatibility (scripts,
    rehearsal notes). The console now drives the split /tests/generate ->
    /tests/run flow instead."""
    target = targets.get_target(payload.target_id)
    cr_text = _cr_text_or_400(payload.tier_name, target=target)
    try:
        result = generate_tests(payload.tier_name, cr_text, target=target)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    run = _run_suite_or_502(target)
    return {
        "label": AI_SUGGESTION_LABEL,
        "diff_text": result.diff_text,
        "files_changed": result.files_changed,
        "used_replay": result.used_replay,
        "pytest_output": run.output,
        "returncode": run.returncode,
        "passed": run.passed,
        "cases": _suite_run_dict(run)["cases"],
        "token_panel": {
            "scoped_input_tokens": result.scoped_input_tokens,
            "scoped_output_tokens": result.scoped_output_tokens,
            "estimated": result.tokens_estimated,
        },
    }


@router.post("/design-doc")
def design_doc(payload: TierRequest, identity: Identity = Depends(require_identity)) -> dict:
    """Draft the internal design doc that hands the applied change off to QA
    — the artifact test generation is written against, sitting between
    "apply" and "generate tests" in the pipeline."""
    target = targets.get_target(payload.target_id)
    cr_text = _cr_text_or_400(payload.tier_name, target=target)
    try:
        text = draft_design_doc(cr_text, target=target)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if payload.ticket_number:
        record_event(payload.ticket_number, "ai", "design_doc_drafted", detail="")
    return {"label": AI_SUGGESTION_LABEL, "design_doc": text}


@router.post("/release-notes")
def release_notes(payload: TierRequest, identity: Identity = Depends(require_identity)) -> dict:
    target = targets.get_target(payload.target_id)
    cr_text = _cr_text_or_400(payload.tier_name, target=target)
    try:
        text = draft_release_notes(cr_text, target=target)
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
    log_path = run_dir / "session.log"
    session_log_tail = (
        log_path.read_text(encoding="utf-8", errors="replace")[-6000:]
        if log_path.exists()
        else ""
    )
    return {
        "label": AI_SUGGESTION_LABEL,
        "status": status_dict,
        "diff_text": diff_text,
        "session_log_tail": session_log_tail,
    }


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


class QuickChatRequest(BaseModel):
    message: str
    reset: bool = False


@router.post("/chat/quick-impact")
def quick_impact_chat(
    payload: QuickChatRequest,
    session_id: str = Depends(require_session_id),
    identity: Identity = Depends(require_identity),
) -> dict:
    """Free-text 'how much would this cost' entry point — asks clarifying
    questions when it needs more detail (capped, see
    docs/design/s3_llm_cost_controls.md), then a final impact/effort answer.

    History is kept server-side in the caller's own login session (same
    in-memory store `api/session.py` already uses for identity) — the client
    only ever sends the latest message, never the transcript.
    """
    session = get_session_data(session_id)
    assert session is not None
    if payload.reset:
        session.pop(_QUICK_CHAT_SESSION_KEY, None)
        if not payload.message.strip():
            # Pure "clear the conversation" call — no LLM call needed.
            return {"label": AI_SUGGESTION_LABEL, "needs_clarification": False}
    history: list[QuickChatTurn] = session.get(_QUICK_CHAT_SESSION_KEY, [])

    try:
        result = continue_session(payload.message, history)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    updated_history = [*history, QuickChatTurn(role="user", text=payload.message)]
    if result.needs_clarification:
        updated_history.append(QuickChatTurn(role="assistant", text=result.question))
    session[_QUICK_CHAT_SESSION_KEY] = updated_history

    response: dict = {
        "label": AI_SUGGESTION_LABEL,
        "needs_clarification": result.needs_clarification,
    }
    if result.needs_clarification:
        response["question"] = result.question
    else:
        assert result.effort_estimate is not None
        response["impact_analysis"] = result.impact_analysis
        response["effort_estimate"] = {
            "hours_class": result.effort_estimate.hours_class,
            "priority_equivalent": result.effort_estimate.priority_equivalent,
            "reasoning": result.effort_estimate.reasoning,
        }
        response["code_change_warranted"] = result.code_change_warranted
        response["suggested_cr_summary"] = result.suggested_cr_summary
    return response
