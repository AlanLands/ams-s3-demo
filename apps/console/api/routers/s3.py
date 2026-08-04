"""S3 REST endpoints -- thin wrappers over s3_enhancement's existing
Enhancement Delivery modules. No business logic lives here; every function
called below is the exact same one the Streamlit view (`s3_enhancement/app.py`)
already called.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from apps.console.api.auth import require_identity, require_session_id
from apps.console.api.session import get_session_data
from common.constants import AI_SUGGESTION_LABEL
from common.gitlab_client import GitLabError, get_client
from common.jira_client import JiraError, get_jira_client
from common.llm import LLMError
from common.roster import Identity
from common.ticket_events import (
    distinct_tickets_with_action,
    events_for,
    events_log_marker,
    record_event,
)
from s3_enhancement import (
    admin_ops,
    applications,
    routing,
    scm,
    scm_live,
    story_intake,
    targets,
    testrun,
)
from s3_enhancement.acceptance import parse_acceptance_criteria
from s3_enhancement.analyze import (
    build_assumption_question,
    check_story_clarity,
    check_story_gaps,
    draft_adhoc_effort_estimate,
    draft_adhoc_impact_analysis,
    draft_cross_team_impact,
    draft_effort_estimate,
    draft_impact_analysis,
)
from s3_enhancement.codegen import (
    add_file_to_proposal,
    apply_change,
    clear_rejection,
    propose_change,
    reject_file,
    rejected_files,
    revert_change,
    revertable_files,
    revise_change,
)
from s3_enhancement.conversation import MAX_CLARIFICATION_TURNS, clarification_turns_used
from s3_enhancement.story import render_story, sanitize_tier_name
from s3_enhancement.design_sync import review_after_apply
from s3_enhancement.designdoc import (
    PdfUnavailableError,
    render_document_html,
    render_pdf,
    render_release_record_html,
)
from s3_enhancement.diagram import build_change_map, build_svg, caption_for
from s3_enhancement.docgen import (
    draft_design_doc,
    draft_release_note_set,
    draft_release_notes,
)
from s3_enhancement.harness import latest_harness_run
from s3_enhancement.quick_chat import QuickChatTurn, continue_session
from s3_enhancement.release import (
    ReleaseRecord,
    SuiteEvidence,
    build_deployment_plan,
    collect_approvals,
    unproven_claims,
)
from s3_enhancement.relevance import (
    discover_files_for_target,
    discover_gitlab_files,
    naive_prompt_tokens,
    select_relevant_files,
)
from s3_enhancement.repo_match import (
    RepoMatch,
    build_confirmation_question,
    needs_confirmation,
    suggest_target_repo,
)
from s3_enhancement.scenarios import (
    draft_scenarios,
    resolve_criteria_refs,
    scenario_from_dict,
    uncovered_criteria,
    validate_scenarios,
)
from s3_enhancement.screenshots import ScreenshotError, capture_form_screenshot
from s3_enhancement.target_match import TargetMatch, resolve_target_for_story
from s3_enhancement.targets import Target
from s3_enhancement.testgen import generate_tests
from s3_enhancement.traceability import build_matrix

_QUICK_CHAT_SESSION_KEY = "s3_quick_chat_history"
_ADHOC_CLARITY_SESSION_KEY = "s3_adhoc_clarity_history"

router = APIRouter(prefix="/s3", tags=["s3"])


class TierRequest(BaseModel):
    tier_name: str
    target_id: str | None = None
    # Optional Jira ticket key this action should be logged against (e.g.
    # "AMS-101") — purely for the Activity feed; the pipeline behaves
    # identically whether or not it's supplied.
    ticket_number: str | None = None


class DesignDocRequest(TierRequest):
    # Applications the cross-team check surfaced, if it was run. Optional
    # because the diagram is useful without them and the check is an
    # independent beat the tester may skip.
    downstream_apps: list[str] = []


class DesignDocExportRequest(DesignDocRequest):
    format: Literal["html", "pdf"] = "pdf"
    include_diagram: bool = True


class ReleaseRequest(TierRequest):
    downstream_apps: list[str] = []
    # Lets the deployment plan and the release record pin themselves to the
    # branch and commit the change went through. The branch state is read
    # server-side from the proposal's own file (see s3_enhancement/scm.py), not
    # posted as a branch name, so a client cannot claim a commit nobody made.
    proposal_id: str | None = None


class ReleaseRecordRequest(ReleaseRequest):
    """Everything the record needs that only the console knows.

    The API is stateless across beats, so the run's results live in the
    browser until something collects them — which is precisely the gap the
    record exists to close. Approvals are the exception: those are read from
    the server-side event log, because "who signed this" must not be
    reported by the same client that is asking for the certificate.
    """

    format: Literal["pdf", "html"] = "pdf"
    scenarios: list[dict] = []
    generated_cases: list[dict] = []
    regression_cases: list[dict] = []
    # {"caught": bool, "total": int, "failed": int} from the seeded-bug beat.
    mutation: dict | None = None
    applied_files: list[str] = []


class ScenarioApprovalRequest(TierRequest):
    # The tester's edited plan, in the same JSON shape the draft returned.
    scenarios: list[dict] = []


class TestsGenerateRequest(TierRequest):
    # Optional: the approved plan to generate against. Absent means "generate
    # from the user story alone", which is what the pre-scenario flow did.
    scenarios: list[dict] | None = None


class TraceabilityRequest(TierRequest):
    """Everything the matrix needs, supplied by the caller.

    The console already holds the approved plan and both runs' results, and
    the API is otherwise stateless across beats — re-running suites here just
    to rebuild a report would be slower and could disagree with what the
    tester is looking at on screen.
    """

    scenarios: list[dict] = []
    generated_cases: list[dict] = []
    regression_cases: list[dict] = []


class AdhocAnalyzeRequest(BaseModel):
    # Free-text ticket content — unlike TierRequest, there's no tier_name/
    # target_id because this is for a ticket with no user story/target registered in
    # this console (e.g. a cross-team ticket raised against another app).
    # On a follow-up call after `needs_clarification: true` came back, this
    # field carries the engineer's answer, not the original ticket text again
    # — same "latest message" semantics as QuickChatRequest.message.
    story_text: str
    ticket_number: str | None = None
    reset_clarification: bool = False
    # ServiceNow application context, when the ticket carries it. Present ->
    # the deterministic route wins and the LLM repo match is skipped entirely.
    ci: str | None = None
    business_service: str | None = None


def _story_text_or_400(tier_name: str, *, target: Target | None = None) -> str:
    clean, error = sanitize_tier_name(tier_name)
    if error:
        raise HTTPException(status_code=422, detail=error)
    assert clean is not None
    return render_story(clean, target=target)


def _run_suite_or_502(target: Target) -> testrun.SuiteRun:
    """Run the target's generated test suite with the target's own runner —
    pytest by default; a target can declare an external invocation instead on
    the Target itself (test_command/test_cwd). A missing runner binary
    surfaces as a clean 502, not an uncaught FileNotFoundError 500."""
    try:
        return testrun.run_suite(target)
    except testrun.TestRunnerNotFoundError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


_MISSING_FEATURE_ERRORS = ("AttributeError", "TypeError", "NameError", "ImportError")


def _unapplied_change_hint(run: testrun.SuiteRun) -> str | None:
    """Set when a failing run looks like the user story was never applied.

    The generated suite is written against the *post*-user story code. Run it against
    the baseline and every test dies on the attribute or keyword the user story was
    supposed to add — which on screen reads as "the AI wrote broken tests",
    the single most damaging way this beat can fail in front of an audience.
    The failures are indistinguishable from a genuine bug unless something
    says so, so this says so.

    Deliberately phrased as a suspicion, not a diagnosis: a real regression
    can raise the same exception types, and claiming certainty we do not have
    is how a presenter gets sent down the wrong path live.
    """
    failed = [case for case in run.cases if case.status not in ("passed", "skipped")]
    if not failed or run.passed:
        return None
    if not all(
        any(err in (case.message or "") for err in _MISSING_FEATURE_ERRORS) for case in failed
    ):
        return None
    return (
        "Every failure is a missing attribute, keyword or name — the signature of "
        "running the generated suite against code the change was never applied to. "
        'Check "Generate the change" and apply the proposal, then run these again.'
    )


def _suite_run_dict(run: testrun.SuiteRun) -> dict:
    return {
        "unapplied_change_hint": _unapplied_change_hint(run),
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


def _token_panel(
    usage: dict, all_files: dict[str, str], selected: dict[str, str] | None = None
) -> dict:
    """Same scoped-vs-naive comparison /s3/generate already shows, for any
    other beat that also reads codebase context through the relevance
    funnel (impact analysis, cross-team impact) — `all_files` is whatever
    that beat's own `discover_files_for_target()` call already produced,
    `selected` the subset `select_relevant_files()` kept."""
    return {
        "scoped_input_tokens": usage.get("input_tokens"),
        "scoped_output_tokens": usage.get("output_tokens"),
        "estimated": bool(usage.get("estimated")),
        "naive_input_tokens_estimate": naive_prompt_tokens(
            usage.get("input_tokens"), all_files, selected
        ),
    }


def _describe_repo_match(match: RepoMatch, projects: list[dict]) -> dict:
    projects_by_id = {str(project.get("id")): project for project in projects}
    project = projects_by_id.get(match.project_id, {})
    return {
        "id": match.project_id,
        "name": project.get("name_with_namespace") or project.get("name"),
        "reasoning": match.reasoning,
        "confidence": match.confidence,
    }


def _route_dict(decision: routing.RouteDecision) -> dict:
    """Shape a routing decision for the console.

    `method` and `automation_available` are kept as distinct fields rather than
    collapsed into one status string: "we know which team owns this" and "we
    can generate code for it" are separate claims, and the console renders them
    differently (see s3_enhancement/routing.py).
    """
    application = decision.application
    return {
        "method": decision.method,
        "routed": decision.routed,
        "matched_on": decision.matched_on,
        "needs_ai_fallback": decision.needs_ai_fallback,
        "automation_available": decision.automation_available,
        "application": (
            {
                "app_id": application.app_id,
                "display_name": application.display_name,
                "business_service": application.business_service,
                "jira_project_key": application.jira_project_key,
                "component_team": application.component_team,
                "tech_stack": application.tech_stack,
                "repo_path": application.repo_path,
            }
            if application
            else None
        ),
        "suggested_assignee": decision.suggested_assignee,
        "candidate_targets": [
            {
                "target_id": target_id,
                "display_name": targets.get_target(target_id).display_name,
            }
            for target_id in decision.candidate_target_ids
        ],
    }


def _ask_clarifying_question(
    session: dict,
    session_key: str,
    history: list[QuickChatTurn],
    latest_text: str,
    question: str,
    ticket_number: str | None,
) -> dict:
    """Record a clarifying question as the next turn in a shared
    conversation history (whatever its source — story-text vagueness, a
    specific missing detail, or repo identity — they all share one
    `needs_clarification`/`question` contract and one turn budget) and
    return the response shape the frontend's single answer box expects."""
    session[session_key] = [
        *history,
        QuickChatTurn(role="user", text=latest_text),
        QuickChatTurn(role="assistant", text=question),
    ]
    if ticket_number:
        record_event(ticket_number, "ai", "clarification_requested", detail=question)
    return {"label": AI_SUGGESTION_LABEL, "needs_clarification": True, "question": question}


def _full_story_text(latest: str, history: list[QuickChatTurn]) -> str:
    """Reconstruct the ticket's full text from the clarification transcript.

    Once any clarification round has happened, `latest` alone is only the
    newest fragment — the engineer's answer to the last question, not the
    original ticket text (see AdhocAnalyzeRequest.story_text's "latest message"
    semantics). The final impact analysis and any repo-match both need the
    whole picture, not just the last reply.
    """
    parts = [turn.text for turn in history if turn.role == "user"]
    parts.append(latest)
    return "\n".join(parts)


def _parse_detail_fields(detail: str) -> dict[str, str]:
    """Parse a `k=v;k=v` event detail.

    Tolerates the single-field form (`problem_id=PRB0012345`) that events
    written before application context existed use — those are already in
    rehearsal logs, and the board reads them on every call.
    """
    fields: dict[str, str] = {}
    for part in detail.split(";"):
        name, sep, value = part.partition("=")
        if sep:
            fields[name.strip()] = value.strip()
    return fields


def _origin_fields(key: str) -> dict:
    """A ticket's intake origin — "problem_record" (created by
    /jira/problem-record-ticket, tagged with the problem_id it was derived
    from, and with the ServiceNow application context that came with it) or
    "business_story" (everything else: the fixed user story demo tickets and
    human-confirmed cross-team tickets). Both origins converge on the
    identical downstream flow; this is presentational only, read from the
    same ticket-events log every other workflow milestone already uses.

    `ci`/`business_service` are what the routing tier consumes
    (s3_enhancement/routing.py). They are absent for tickets that arrived
    without application context, which is a routable state — the console
    falls back to the AI repo match — not a missing-data error.
    """
    # Last matching event wins, not the first. Normally there is exactly one,
    # but re-running demo/seed_problem_record_ticket.py with a different
    # SEED_CI against the same events log appends a second — and the intent
    # there is plainly to re-route the ticket, not to keep the stale CI.
    latest: dict[str, str] | None = None
    for event in events_for(key):
        if event.get("action") == "problem_record_ticket_created":
            latest = _parse_detail_fields(event.get("detail", ""))
    if latest is None:
        return {"origin": "business_story"}
    return {
        "origin": "problem_record",
        "problem_id": latest.get("problem_id", ""),
        "ci": latest.get("ci", ""),
        "business_service": latest.get("business_service", ""),
    }


def _story_link_fields(key: str) -> dict:
    """Which user story file a ticket was auto-opened from, and the target that user story
    resolved to — `{}` for every ticket that wasn't (the seeded demo user stories,
    cross-team, problem-record).

    Derived fresh from the ticket-events log every call, exactly like
    `_origin_fields`, so nothing has to be stored on the issue itself. This
    is also what keeps `resolve_target_for_story` off the board's hot path: the
    resolution is done once, when the user story is first seen, and read back from
    here on every board load afterwards (see `_story_board_rows`).
    """
    latest: dict[str, str] | None = None
    for event in events_for(key):
        if event.get("action") == story_intake.TICKET_CREATED_ACTION:
            latest = _parse_detail_fields(event.get("detail", ""))
    if latest is None:
        return {}
    fields = {"story_file": latest.get("story_file", "")}
    # Absent, not empty, when the user story resolved to no registered target — an
    # unresolved user story is a perfectly valid ticket (the console's own
    # /target/resolve is still there to try again), and a blank target_id
    # would read as "resolved to nothing" rather than "not resolved".
    if latest.get("target_id"):
        fields["target_id"] = latest["target_id"]
        fields["target_display_name"] = latest.get("target_display_name", "")
        fields["target_method"] = latest.get("target_method", "")
    return fields


class RouteRequest(BaseModel):
    # ServiceNow application context. Both optional: a ticket that carries
    # neither is exactly the case the LLM fallback exists for, and must not be
    # a 422 — "unroutable" is an answer this endpoint returns, not an error.
    ci: str | None = None
    business_service: str | None = None
    ticket_number: str | None = None


@router.post("/route")
def route(payload: RouteRequest, identity: Identity = Depends(require_identity)) -> dict:
    """Resolve a ticket's application from its CI, before any automation runs.

    The deterministic tier only. When this answers `needs_ai_fallback: true`,
    the console's next step is `/analyze-adhoc`, whose existing
    `repo_match` path guesses the repo from the ticket text and asks the
    developer to confirm anything below high confidence.

    Deliberately not folded into `/analyze`: routing decides *whether the
    right repo is even in this console*, which is a question that has to be
    answerable before an analysis is commissioned against a target.
    """
    decision = routing.route_ticket(
        ci=payload.ci, business_service=payload.business_service
    )

    if payload.ticket_number:
        detail = (
            f"{decision.application.display_name} "
            f"({decision.application.component_team}) via {decision.method}"
            if decision.routed
            else "no CI match — falling back to AI repo match"
        )
        record_event(payload.ticket_number, "system", "ticket_routed", detail=detail)

    return _route_dict(decision)


_CRS_ROOT = targets.REPO_ROOT / "stories"


class TargetResolveRequest(BaseModel):
    # Exactly one of these two. story_file is the common case: the console
    # already knows which user story a ticket links to (see S3.tsx's TICKET_CRS) but
    # not which target it resolves to — that's the whole point of this
    # endpoint — so it names the file under stories/ and the server reads it,
    # rather than the client fetching and re-posting the user story's own text.
    # story_text remains for the ad-hoc/cross-team case where there's no
    # committed user story file at all.
    story_file: str | None = None
    story_text: str | None = None
    ticket_number: str | None = None


def _read_story_file_or_4xx(story_file: str) -> str:
    """Read a user story by bare filename from `stories/`.

    Filename only, no path components — the client names *which* user story, never
    *where* to read from, so this can never escape stories/.
    """
    if "/" in story_file or "\\" in story_file or not story_file.endswith(".md"):
        raise HTTPException(status_code=422, detail="story_file must be a bare *.md filename")
    story_path = _CRS_ROOT / story_file
    if not story_path.is_file():
        raise HTTPException(status_code=404, detail=f"no such user story file: {story_file}")
    return story_path.read_text(encoding="utf-8").strip()


@router.get("/story/file")
def story_file(story_file: str, identity: Identity = Depends(require_identity)) -> dict:
    """A user story's own text, by filename, with no target involved.

    `/s3/story` renders a *target's* registered user story template, which presupposes
    the target is already known. This endpoint exists for the case where it
    isn't yet: a user story that names no target system has to be read and analyzed
    before anything can resolve it to a repo (see the console's ad-hoc
    analysis path). Serving the file verbatim keeps that flow reading the
    same user story the resolver reads, rather than a second copy of the request
    pasted into a ticket description.
    """
    return {"story_file": story_file, "story_text": _read_story_file_or_4xx(story_file)}


def _target_match_dict(match: TargetMatch) -> dict:
    return {
        "method": match.method,
        "resolved": match.resolved,
        "needs_confirmation": match.needs_confirmation,
        "confidence": match.confidence if match.method == "ai" else None,
        "reasoning": match.reasoning if match.method == "ai" else "",
        "target_id": match.target.target_id if match.target is not None else None,
        "display_name": match.target.display_name if match.target is not None else None,
        # Every candidate the AI tier weighed, best first — empty for the
        # deterministic tiers, which compared nothing (see RankedCandidate).
        "ranking": [
            {
                "target_id": candidate.target_id,
                "display_name": candidate.display_name,
                "score": candidate.score,
                "reasoning": candidate.reasoning,
            }
            for candidate in match.ranking
        ],
    }


@router.post("/target/resolve")
def resolve_target(
    payload: TargetResolveRequest, identity: Identity = Depends(require_identity)
) -> dict:
    """Resolve a user story's text to one of this console's registered targets.

    Cheapest tier first (see s3_enhancement/target_match.py): the user story's own
    `US-YYYY-NNN:` identifier against every registered target's
    `story_template_path`, then its `Application:` header against the
    applications registry, and only then an LLM guess across the registered
    targets. This is what lets onboarding a new repo mean "register a Target
    and drop its user story under stories/" instead of also editing a ticket-key lookup
    table in the console.
    """
    if payload.story_file and payload.story_text:
        raise HTTPException(
            status_code=422, detail="pass exactly one of story_file or story_text, not both"
        )
    if payload.story_file:
        story_text = _read_story_file_or_4xx(payload.story_file)
    elif payload.story_text:
        story_text = payload.story_text.strip()
    else:
        raise HTTPException(status_code=422, detail="story_file or story_text is required")

    if not story_text:
        raise HTTPException(status_code=422, detail="story_text must not be empty")

    match = resolve_target_for_story(story_text)

    if payload.ticket_number:
        detail = (
            f"{match.target.display_name} via {match.method}"
            if match.resolved
            else "no target match — user story text didn't resolve to a registered target"
        )
        record_event(payload.ticket_number, "system", "target_resolved", detail=detail)

    return _target_match_dict(match)


@router.get("/applications")
def list_applications(identity: Identity = Depends(require_identity)) -> dict:
    """The routing registry, for the console's Applications panel — every
    application S3 can route a ticket to, automatable or not."""
    return {
        "applications": [
            {
                "app_id": app.app_id,
                "display_name": app.display_name,
                "business_service": app.business_service,
                "ci_names": list(app.ci_names),
                "jira_project_key": app.jira_project_key,
                "component_team": app.component_team,
                "tech_stack": app.tech_stack,
                "repo_path": app.repo_path,
                "automation_available": bool(
                    app.automation_available
                    and targets.targets_for_application(app.app_id)
                ),
            }
            for app in applications.all_applications()
        ]
    }


@router.get("/reset-marker")
def reset_marker(identity: Identity = Depends(require_identity)) -> dict:
    """Changes whenever the ticket-events log is cleared (e.g. demo/reset_s3.sh
    between rehearsals). The frontend compares this against what it last saw
    to know its localStorage-cached per-ticket analysis/proposal state is
    stale and should be dropped, instead of showing results for a ticket the
    server no longer has any record of."""
    return {"marker": events_log_marker()}


@router.get("/story")
def story(
    tier_name: str = "Elite",
    target_id: str | None = None,
    identity: Identity = Depends(require_identity),
) -> dict:
    clean, error = sanitize_tier_name(tier_name)
    if error:
        raise HTTPException(status_code=422, detail=error)
    assert clean is not None
    target = targets.get_target(target_id)
    return {"tier_name": clean, "story_text": render_story(clean, target=target)}


class AnalyzeRequest(TierRequest):
    # Set only when responding to a prior needs_clarification: true for this
    # same user story — carries the engineer's answer to the outstanding question.
    # Unlike AdhocAnalyzeRequest.story_text, tier_name/target_id here always
    # render the same fixed user story text (see _story_text_or_400), so there's no
    # "latest message" ambiguity on tier_name itself to resolve.
    clarification_answer: str | None = None
    reset_clarification: bool = False


def _analyze_session_key(tier_name: str, target_id: str | None) -> str:
    return f"s3_analyze_clarity_history:{tier_name}:{target_id or ''}"


@router.post("/analyze")
def analyze(
    payload: AnalyzeRequest,
    session_id: str = Depends(require_session_id),
    identity: Identity = Depends(require_identity),
) -> dict:
    """Impact analysis for one of the console's pinned user story templates.

    Two gates run before an analysis is returned, sharing one budget of at
    most `MAX_CLARIFICATION_TURNS` questions (not one each):

    1. Before drafting, `analyze.check_story_gaps` screens the user story text for a
       specific missing detail (an unstated default, threshold, or scope
       boundary) the analysis would otherwise have to guess at.
    2. After drafting, any assumption the draft itself declared is asked
       about via `analyze.build_assumption_question`, and the draft is
       withheld until it's answered. Gate 1 predicts what the model might
       guess at from the user story text alone and is regularly wrong in both
       directions; this one reads what the model actually did guess, so the
       "assumptions the AI made" box can only ever appear once the turn
       budget is spent — never as the first thing the engineer sees.

    Both use the same needs_clarification/question contract and per-login-
    session history as /analyze-adhoc's gates. Answers, once given, are
    folded into the user story text handed to the analysis/effort calls, which then
    re-draft off the fold-in rather than the pinned demo recording (see
    `draft_impact_analysis`'s `pin_cache`).
    """
    target = targets.get_target(payload.target_id)
    story_text = _story_text_or_400(payload.tier_name, target=target)

    session = get_session_data(session_id)
    assert session is not None
    session_key = _analyze_session_key(payload.tier_name, payload.target_id)
    if payload.reset_clarification:
        session.pop(session_key, None)
    history: list[QuickChatTurn] = session.get(session_key, [])

    try:
        gaps = check_story_gaps(story_text, history)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if gaps.needs_clarification:
        return _ask_clarifying_question(
            session, session_key, history, payload.clarification_answer or "", gaps.question,
            payload.ticket_number,
        )

    # `history`'s "user" turns are prior answers only (see _ask_clarifying_
    # question) — the current call's answer, if any, was never appended to
    # history since this is the call that resolved the gate rather than
    # asking again, so it must be added explicitly here.
    answers = [turn.text for turn in history if turn.role == "user" and turn.text]
    if payload.clarification_answer:
        answers.append(payload.clarification_answer)
    effective_story_text = story_text
    if answers:
        effective_story_text = f"{story_text}\n\nAdditional detail from the engineer:\n" + "\n".join(
            answers
        )

    usage: dict = {}
    try:
        impact = draft_impact_analysis(
            effective_story_text, target=target, usage_out=usage, pin_cache=not answers
        )
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    # Anything the draft had to assume gets asked, not shipped in an
    # "assumptions the AI made" box the engineer never agreed to — the box
    # only appears once the shared turn budget is genuinely spent (below).
    if impact.assumptions and clarification_turns_used(history) < MAX_CLARIFICATION_TURNS:
        return _ask_clarifying_question(
            session, session_key, history, payload.clarification_answer or "",
            build_assumption_question(impact.assumptions), payload.ticket_number,
        )

    session.pop(session_key, None)
    try:
        effort = draft_effort_estimate(effective_story_text, target=target, pin_cache=not answers)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    all_files = discover_files_for_target(target, story_text)
    selection = select_relevant_files(
        story_text, all_files, core_files=target.core_files, design_doc_root=target.root
    )
    # Part of the analysis, not a button next to it. Asked for on the 2026-08-03
    # walkthrough: "why do we have to prompt it — it should come automatically
    # in the main analysis itself. If somebody forgets to click the button then
    # we lose that impact analysis for the other teams."
    #
    # Deliberately a *second* call rather than one merged prompt: the two beats
    # have separate cache keys, and folding them into one prompt would strand
    # both recordings. A failure here degrades to "not checked" rather than
    # taking the whole analysis down with it — the analysis is the beat, the
    # cross-team list is an addition to it.
    cross_team: list[dict] | None = None
    try:
        cross_team = [
            {
                "app_name": item.app_name,
                "reason": item.reason,
                "suggested_summary": item.suggested_summary,
                "description": item.description,
            }
            for item in draft_cross_team_impact(story_text, target=target, usage_out=usage)
        ]
    except LLMError:
        cross_team = None

    if payload.ticket_number:
        record_event(
            payload.ticket_number,
            "ai",
            "impact_analysis_drafted",
            detail=f"{effort.hours_class} / {effort.priority_equivalent}",
        )
        if cross_team is not None:
            record_event(
                payload.ticket_number,
                "ai",
                "cross_team_impact_checked",
                detail=", ".join(item["app_name"] for item in cross_team) or "none found",
            )
    return {
        "label": AI_SUGGESTION_LABEL,
        "needs_clarification": False,
        "impact_analysis": impact.text,
        "assumptions": impact.assumptions,
        "effort_estimate": {
            "hours_class": effort.hours_class,
            "priority_equivalent": effort.priority_equivalent,
            "reasoning": effort.reasoning,
        },
        "cross_team_impacts": cross_team,
        "file_selection": _selection_dict(selection),
        "token_panel": _token_panel(usage, all_files, selection.selected),
    }


@router.post("/analyze-adhoc")
def analyze_adhoc(
    payload: AdhocAnalyzeRequest,
    session_id: str = Depends(require_session_id),
    identity: Identity = Depends(require_identity),
) -> dict:
    """Impact analysis for a ticket with no linked user story/target in this console
    (e.g. a cross-team ticket for another application) — runs directly off
    the ticket's own text instead of one of the two pinned user story templates, so
    there's no codebase/file_selection to report.

    Three clarification gates run before an analysis is produced, sharing
    one conversational budget of at most `MAX_CLARIFICATION_TURNS` follow-up
    questions total (not each): `analyze.check_story_clarity` for overall
    story-text vagueness, then `analyze.check_story_gaps` for a specific missing
    detail (an unstated default/threshold/scope boundary that would
    otherwise be silently guessed and reported as an assumption instead of
    asked about), then — once the text itself is clear enough, and only if a
    live GitLab connection is configured — a repo-identity check via
    `repo_match.suggest_target_repo`. Each asks through the exact same
    question/answer turn this endpoint already uses, rather than a separate
    action; if GitLab isn't reachable the repo check is skipped entirely and
    analysis proceeds same as before this existed. History is kept
    server-side in the caller's own login session, same mechanism
    /chat/quick-impact uses.
    """
    story_text = payload.story_text.strip()
    if not story_text:
        raise HTTPException(status_code=422, detail="story_text must not be empty")
    if len(story_text) > 4000:
        raise HTTPException(status_code=422, detail="story_text is too long (max 4000 characters)")

    session = get_session_data(session_id)
    assert session is not None
    if payload.reset_clarification:
        session.pop(_ADHOC_CLARITY_SESSION_KEY, None)
    history: list[QuickChatTurn] = session.get(_ADHOC_CLARITY_SESSION_KEY, [])

    try:
        clarity = check_story_clarity(story_text, history)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if clarity.needs_clarification:
        return _ask_clarifying_question(
            session, _ADHOC_CLARITY_SESSION_KEY, history, story_text, clarity.question,
            payload.ticket_number,
        )

    try:
        gaps = check_story_gaps(story_text, history)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if gaps.needs_clarification:
        return _ask_clarifying_question(
            session, _ADHOC_CLARITY_SESSION_KEY, history, story_text, gaps.question,
            payload.ticket_number,
        )

    full_story_text = _full_story_text(story_text, history)

    # Deterministic routing first. When the ticket names a CI the registry
    # knows, the answer is already settled: no model call, no confirmation
    # turn, and the LLM repo match below is skipped rather than run and
    # discarded — the cost saving is the point of the tier, not a side effect.
    route_decision = routing.route_ticket(
        ci=payload.ci, business_service=payload.business_service
    )

    target_repo: dict | None = None
    projects = None
    if route_decision.needs_ai_fallback:
        try:
            projects = get_client().list_projects()
        except GitLabError:
            projects = None

    if projects:
        try:
            suggestion = suggest_target_repo(full_story_text, projects)
        except LLMError:
            # Repo identity is a bonus signal on top of the analysis, not a
            # dependency of it — an LLM hiccup here shouldn't block the
            # analysis the engineer actually asked for.
            suggestion = None
        if suggestion is not None:
            if (
                needs_confirmation(suggestion.best_match)
                and clarification_turns_used(history) < MAX_CLARIFICATION_TURNS
            ):
                question = build_confirmation_question(suggestion, projects)
                return _ask_clarifying_question(
                    session, _ADHOC_CLARITY_SESSION_KEY, history, story_text, question,
                    payload.ticket_number,
                )
            target_repo = _describe_repo_match(suggestion.best_match, projects)

    try:
        impact = draft_adhoc_impact_analysis(full_story_text)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    # Same assumptions-become-questions gate as /analyze — see that
    # endpoint's docstring for why the draft's own assumptions, not a
    # pre-draft prediction of them, are what's worth asking about.
    if impact.assumptions and clarification_turns_used(history) < MAX_CLARIFICATION_TURNS:
        return _ask_clarifying_question(
            session, _ADHOC_CLARITY_SESSION_KEY, history, story_text,
            build_assumption_question(impact.assumptions), payload.ticket_number,
        )

    session.pop(_ADHOC_CLARITY_SESSION_KEY, None)
    try:
        effort = draft_adhoc_effort_estimate(full_story_text)
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
        "needs_clarification": False,
        "impact_analysis": impact.text,
        "assumptions": impact.assumptions,
        "effort_estimate": {
            "hours_class": effort.hours_class,
            "priority_equivalent": effort.priority_equivalent,
            "reasoning": effort.reasoning,
        },
        "target_repo": target_repo,
        "routing": _route_dict(route_decision),
    }


@router.post("/impact/cross-team")
def cross_team_impact(payload: TierRequest, identity: Identity = Depends(require_identity)) -> dict:
    """AI-suggested list of other application teams this user story would also
    require work from — a human confirms each one via /jira/cross-team-ticket
    before any ticket is actually created."""
    target = targets.get_target(payload.target_id)
    story_text = _story_text_or_400(payload.tier_name, target=target)
    usage: dict = {}
    try:
        impacts = draft_cross_team_impact(story_text, target=target, usage_out=usage)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    all_files = discover_files_for_target(target, story_text)
    selection = select_relevant_files(
        story_text, all_files, core_files=target.core_files, design_doc_root=target.root
    )
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
                "description": impact.description,
            }
            for impact in impacts
        ],
        "token_panel": _token_panel(usage, all_files, selection.selected),
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


class ProblemRecordTicketRequest(BaseModel):
    summary: str
    description: str = ""
    # Synthetic problem-record id from the incident-reduction pipeline (a
    # separate workstream — see CLAUDE.md) this ticket is derived from, e.g.
    # "PRB0012345". Illustrative only: this console has no live connection to
    # that pipeline, it just carries the id through so the board/ticket
    # modal can show the linkage the team asked for.
    problem_id: str
    assignee: str | None = None
    # ServiceNow application context carried from the problem record, so the
    # derived ticket can be routed deterministically (see /s3/route). Optional:
    # a problem record without a CI still creates a perfectly valid ticket.
    ci: str | None = None
    business_service: str | None = None


@router.post("/jira/problem-record-ticket")
def create_problem_record_ticket(
    payload: ProblemRecordTicketRequest, identity: Identity = Depends(require_identity)
) -> dict:
    """Create a ticket tagged as originating from a problem record (repeated
    incidents -> a permanent-fix problem record -> this user story) rather than a
    direct business user story — the second of S3's two intake flavors.
    Runs through the exact same downstream flow as any other ticket
    (clarity-gated ad-hoc analyze, codegen, tests, docs); only the origin tag
    and problem_id differ, both purely presentational.
    """
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
    detail = f"problem_id={payload.problem_id}"
    if payload.ci:
        detail += f";ci={payload.ci}"
    if payload.business_service:
        detail += f";business_service={payload.business_service}"
    record_event(new_key, "system", "problem_record_ticket_created", detail=detail)

    # Record the routing decision as its own event, so the Activity feed shows
    # the ticket reaching a team before any AI step runs against it.
    decision = routing.route_ticket(ci=payload.ci, business_service=payload.business_service)
    if decision.routed:
        record_event(
            new_key,
            "system",
            "ticket_routed",
            detail=(
                f"{decision.application.display_name} "
                f"({decision.component_team}) via {decision.method}"
            ),
        )

    return {
        "label": AI_SUGGESTION_LABEL,
        "issue": {**issue, **_origin_fields(new_key)},
        "routing": _route_dict(decision),
    }


class AssignTicketRequest(BaseModel):
    key: str
    # None (or omitted) unassigns, putting the ticket back in the manager's
    # queue. Reassignment needs no separate field: this endpoint has always
    # been unconditional, and `assign_issue` overwrites.
    assignee: str | None = None


@router.post("/jira/assign-ticket")
def assign_ticket(
    payload: AssignTicketRequest, identity: Identity = Depends(require_identity)
) -> dict:
    """Assign, reassign, or unassign an already-created ticket — split from
    creation so a ticket can land as open/unassigned first and a manager can
    pick the assignee later, on their own schedule, and change their mind
    afterwards.

    Not manager-only, and the reason is the QA hand-off: the engineer assigns
    the tester and moves the ticket to QA themselves. Gating the whole endpoint
    on the manager role breaks that beat with "Manager role required" at the
    hand-off card.

    What is actually worth refusing is one caller taking a ticket **off**
    someone else. So: a manager may do anything; anyone else may pick up an
    unassigned ticket or hand on a ticket already assigned to them. Checked
    server-side against the ticket's current assignee, never against a role the
    client posts — same rule as `scm.commit_blockers` and the release record's
    approvals (see CLAUDE.md).
    """
    assignee = (payload.assignee or "").strip() or None
    if identity.role != "manager":
        try:
            current = (get_jira_client().get_issue(payload.key) or {}).get("assignee")
        except JiraError:
            # Never let an inability to read the current holder turn into a
            # silent grant — refuse and let a manager do it.
            current = None
        if current not in (None, "", identity.name):
            raise HTTPException(
                status_code=403,
                detail=(
                    f"{payload.key} is assigned to {current}. Only a manager can "
                    f"reassign someone else's ticket."
                ),
            )
    try:
        issue = get_jira_client().assign_issue(payload.key, assignee)
    except JiraError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    # Separate actions, not one action with an empty detail: the timeline is
    # the audit trail a reviewer reads, and "unassigned" is a different event
    # from "assigned to nobody".
    if assignee is None:
        record_event(payload.key, "human", "ticket_unassigned", detail="")
    else:
        record_event(payload.key, "human", "ticket_assigned", detail=assignee)
    return {"label": AI_SUGGESTION_LABEL, "issue": issue}


class TicketStatusRequest(BaseModel):
    key: str
    status: str


@router.post("/jira/ticket-status")
def set_ticket_status(
    payload: TicketStatusRequest, identity: Identity = Depends(require_identity)
) -> dict:
    """Mark a ticket's status — e.g. the assigned team logs in, does their
    part, and marks their cross-team ticket Done so the original user story's
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
    """Cross-team tickets linked to a primary user story ticket, with their current
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
    # Names the feature branch apply opens (see s3_enhancement/scm.py). Absent
    # falls back to the default target rather than skipping the branch: the
    # branch-before-write framing is the point of the beat, so it must not be
    # something a caller can drop by omitting a field.
    target_id: str | None = None


class DesignSyncRequest(BaseModel):
    proposal_id: str
    applied_files: list[str] = []
    ticket_number: str | None = None
    target_id: str | None = None


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
    story_text = _story_text_or_400(payload.tier_name, target=target)
    try:
        result = propose_change(payload.tier_name, story_text, target=target)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    all_files = discover_files_for_target(target, story_text)
    selection = select_relevant_files(
        story_text, all_files, core_files=target.core_files, design_doc_root=target.root
    )
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
    SQLite schema so a user story that adds a column doesn't crash the running
    portal. Subprocesses, not in-process imports, so each step runs against
    the newly written module files rather than whatever this API process
    imported at startup. This is target-registry-driven on purpose: any new
    user story against a registered root inherits its migration step automatically.

    Returns {"ok": bool, "steps": [...]} so a migration crash — the applied
    user story broke the app — reaches the caller with its traceback instead of
    dying silently in a discarded subprocess result.
    """
    # Anchored on the target registry rather than counted parent hops: this
    # module has already moved once (api/ -> apps/console/api/), and a stale
    # hop count fails silently by matching no target root at all, which looks
    # like "the migration step just didn't run".
    repo_root = targets.REPO_ROOT
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
    staged file instead of the whole proposal.

    Opens the change's feature branch *before* the first write (see
    s3_enhancement/scm.py). The branch is modelled, not real — but it is opened
    in the right order, because "you branch, then you edit" is the part of the
    flow this beat is here to show, and back-filling it after the write would
    misrepresent it.
    """
    target = targets.get_target(payload.target_id)
    branch = scm.open_branch(
        payload.proposal_id, payload.ticket_number or "", target.target_id
    )
    branch_was_new = not branch.staged_files and branch.commit is None
    try:
        applied_files = apply_change(payload.proposal_id, payload.file_path)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    branch = scm.record_applied(payload.proposal_id, applied_files) or branch
    post_apply = _run_post_apply(applied_files, payload.ticket_number)

    if payload.ticket_number:
        if branch_was_new:
            record_event(
                payload.ticket_number,
                "system",
                "branch_opened",
                detail=f"{branch.branch} (off {branch.base}) — simulated",
            )
        record_event(
            payload.ticket_number,
            "human",
            "code_change_applied",
            detail=payload.file_path or payload.proposal_id,
        )

    # Applying wrote the files; the target process is still serving the old code
    # from memory until it is restarted. Without this the console's "the app now
    # has this capability — open the console to try it" is false at the exact
    # moment the audience goes and checks, which is the worst possible time for
    # it to be false. Restart is part of Apply rather than a button next to it
    # for the same reason the cross-team check is (see /s3/analyze).
    restarts: list[dict] = []
    if target.application_id:
        try:
            restarts = admin_ops.restart_application(target.application_id)
        except Exception:  # noqa: BLE001 - reported below, never fatal
            restarts = []
    # A failed or impossible restart must not read as success: the UI keys off
    # this to say "restart it yourself" instead of inviting a click-through to
    # behaviour that has not changed yet.
    restarted = bool(restarts) and all(item.get("ok") for item in restarts)
    if payload.ticket_number and restarts:
        record_event(
            payload.ticket_number,
            "system",
            "target_app_restarted" if restarted else "target_app_restart_failed",
            detail=", ".join(f"{item.get('id')}: {item.get('detail', '')}" for item in restarts),
        )
    return {
        "proposal_id": payload.proposal_id,
        "applied_files": applied_files,
        "post_apply": post_apply,
        "rejected_files": rejected_files(payload.proposal_id),
        "revertable_files": revertable_files(payload.proposal_id),
        "scm": branch.to_dict(),
        "restarted": restarted,
        "restarts": restarts,
    }


class RejectRequest(BaseModel):
    proposal_id: str
    file_path: str
    # Why the developer turned this file down. Free text, optional — an
    # unexplained rejection is still a decision worth recording, and demanding
    # a justification would just produce empty ones.
    reason: str = ""
    ticket_number: str | None = None


@router.post("/reject")
def reject(payload: RejectRequest, identity: Identity = Depends(require_identity)) -> dict:
    """Reject one file of a staged proposal, with an optional reason.

    The counterpart to per-file Apply: it excludes the file from a subsequent
    whole-proposal apply *and* writes the decision to the ticket's audit trail,
    so "the developer declined this change, and why" is recoverable later
    rather than being indistinguishable from "nobody got to it".
    """
    try:
        rejections = reject_file(payload.proposal_id, payload.file_path, payload.reason)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if payload.ticket_number:
        detail = payload.file_path
        if payload.reason.strip():
            detail += f" — {payload.reason.strip()}"
        record_event(payload.ticket_number, "human", "code_change_rejected", detail=detail)

    return {"proposal_id": payload.proposal_id, "rejected_files": rejections}


class ClearRejectionRequest(BaseModel):
    proposal_id: str
    file_path: str
    ticket_number: str | None = None


@router.post("/reject/clear")
def clear_reject(
    payload: ClearRejectionRequest, identity: Identity = Depends(require_identity)
) -> dict:
    """Undo a rejection, putting the file back in play before anything is
    applied — the developer is allowed to change their mind."""
    rejections = clear_rejection(payload.proposal_id, payload.file_path)

    if payload.ticket_number:
        record_event(
            payload.ticket_number,
            "human",
            "code_change_rejection_cleared",
            detail=payload.file_path,
        )

    return {"proposal_id": payload.proposal_id, "rejected_files": rejections}


class RevertRequest(BaseModel):
    proposal_id: str
    # If set, revert only this one applied file; otherwise revert everything
    # this proposal applied.
    file_path: str | None = None
    ticket_number: str | None = None


@router.post("/revert")
def revert(payload: RevertRequest, identity: Identity = Depends(require_identity)) -> dict:
    """Put the working tree back the way it was before this proposal was
    applied — file-by-file or wholesale.

    Apply writes to the real repo, so before this the only undo was a full
    demo reset, which discards every other beat's state too. The post-apply
    migration re-runs afterwards for the same reason it runs on apply: the
    working tree changed, and the running app has to stay consistent with it.
    """
    try:
        reverted_files = revert_change(payload.proposal_id, payload.file_path)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    post_apply = _run_post_apply(reverted_files, payload.ticket_number)
    # Reverting every applied file abandons the branch rather than rewinding it:
    # a commit that exists on a branch is not unmade by an undo button, and
    # pretending otherwise would be the one dishonest step in the flow.
    branch = scm.record_reverted(payload.proposal_id, reverted_files)

    if payload.ticket_number:
        record_event(
            payload.ticket_number,
            "human",
            "code_change_reverted",
            detail=payload.file_path or payload.proposal_id,
        )
        if branch is not None and branch.abandoned_at:
            record_event(
                payload.ticket_number,
                "system",
                "branch_abandoned",
                detail=f"{branch.branch} — every applied file was reverted",
            )

    return {
        "proposal_id": payload.proposal_id,
        "reverted_files": reverted_files,
        "post_apply": post_apply,
        "revertable_files": revertable_files(payload.proposal_id),
        "scm": branch.to_dict() if branch else None,
    }


# --- the source-control flow around Apply -----------------------------------
#
# Every response below carries `simulated: true` and a `transcript` of the git
# commands a real integration would have run. Nothing here executes git — see
# s3_enhancement/scm.py for why that is load-bearing rather than a shortcut,
# and do not "fix" the simulation into a fake success.


class ScmCheckoutRequest(BaseModel):
    ticket_number: str
    target_id: str


@router.post("/scm/checkout")
def scm_checkout(
    payload: ScmCheckoutRequest, identity: Identity = Depends(require_identity)
) -> dict:
    """Step 0, "Check out the repo": cut (or switch to) this user story's feature
    branch before anything is generated.

    Simulated by default — same convention `/s3/release/attach` uses under
    JIRA_MODE=replay: a computed branch name, no `sha`, clearly labelled.
    Set SCM_MODE=live to run a real local `git checkout -b` / `git checkout`
    in this repo. Still branch-only even then: no commit, no push, no
    remote — see s3_enhancement/scm_live.py for why that stays a separate,
    narrower module rather than an extension of scm.py's modelled flow.
    """
    branch = scm.branch_name_for(payload.ticket_number, payload.target_id)
    if not scm_live.live_mode_enabled():
        record_event(
            payload.ticket_number,
            "human",
            "repo_checked_out",
            detail=branch,
        )
        return {
            "mode": "simulated",
            "branch": branch,
            "base": scm.BASE_BRANCH,
            "sha": None,
            "created": None,
            "already_current": None,
            "dirty_files": [],
            "detail": None,
        }

    try:
        result = scm_live.checkout_branch(payload.ticket_number, payload.target_id)
    except scm_live.ScmLiveError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    record_event(
        payload.ticket_number,
        "human",
        "repo_checked_out",
        detail=f"{result.branch} @ {result.sha}",
    )
    return {**result.to_dict(), "detail": None}


class ScmRequest(BaseModel):
    proposal_id: str
    ticket_number: str | None = None
    target_id: str | None = None


class ScmCommitRequest(ScmRequest):
    # Optional override for the generated subject line. The default is assembled
    # from the ticket and user story label (scm.commit_message_for) rather than drafted
    # by the model — no cache key, nothing to be confidently wrong about.
    message: str | None = None


def _scm_payload(proposal_id: str, ticket_number: str | None) -> dict:
    """Branch state plus the gate's reasoning, as the console renders it."""
    state = scm.state_for(proposal_id)
    events = events_for(ticket_number) if ticket_number else []
    return {
        "proposal_id": proposal_id,
        "scm": state.to_dict() if state else None,
        "commit_blockers": scm.commit_blockers(events),
        "test_evidence": scm.evidence_summary(events),
    }


@router.get("/scm")
def scm_state(
    proposal_id: str,
    ticket_number: str | None = None,
    identity: Identity = Depends(require_identity),
) -> dict:
    """Where this proposal's change sits in the branch → commit → push flow."""
    return _scm_payload(proposal_id, ticket_number)


@router.post("/scm/commit")
def scm_commit(
    payload: ScmCommitRequest, identity: Identity = Depends(require_identity)
) -> dict:
    """Commit the applied files onto the change's feature branch.

    Gated on the ticket's own event log, not on a flag from the browser: the
    generated suite must have run and passed, and the pre-existing regression
    suite must not be failing. Reading the gate server-side is the same rule the
    release record's approvals follow — a client that could assert "tests
    passed" could commit a red branch, which would make the beat's central
    claim false.
    """
    if not payload.ticket_number:
        raise HTTPException(
            status_code=422,
            detail="A ticket number is required to commit — the gate reads the ticket's test results.",
        )
    blockers = scm.commit_blockers(events_for(payload.ticket_number))
    if blockers:
        raise HTTPException(status_code=409, detail=" ".join(blockers))

    target = targets.get_target(payload.target_id)
    message = payload.message or scm.commit_message_for(
        payload.ticket_number,
        _story_label_for(target),
        scm.summary_from_display_name(target.display_name),
    )
    try:
        state = scm.commit_branch(payload.proposal_id, message)
    except scm.ScmError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    record_event(
        payload.ticket_number,
        "human",
        "change_committed",
        detail=(
            f"{state.commit.sha} on {state.branch}: {state.commit.message} "
            f"({len(state.commit.files)} file(s)) — simulated"
        ),
    )
    return _scm_payload(payload.proposal_id, payload.ticket_number)


@router.post("/scm/push")
def scm_push(payload: ScmRequest, identity: Identity = Depends(require_identity)) -> dict:
    """Push the branch and queue the deployment pipeline — modelled, not run.

    The honest counterpart to the commit step: no remote is contacted, so the
    response says `simulated: true` and the release record counts the pipeline
    as something this release did *not* evidence. The same convention
    `/s3/release/attach` uses under JIRA_MODE=replay.
    """
    try:
        state = scm.push_branch(payload.proposal_id)
    except scm.ScmError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if payload.ticket_number:
        record_event(
            payload.ticket_number,
            "system",
            "branch_pushed",
            detail=f"{state.branch} → {scm.REMOTE}, {state.pipeline_id} queued — simulated",
        )
    return {
        **_scm_payload(payload.proposal_id, payload.ticket_number),
        "detail": (
            f"{state.branch} would be pushed to {scm.REMOTE} and {state.pipeline_id} "
            "queued. This console does not contact a remote — the push and the "
            "pipeline run are simulated."
        ),
    }


@router.post("/design-sync")
def design_sync(
    payload: DesignSyncRequest, identity: Identity = Depends(require_identity)
) -> dict:
    """After an Apply, check whether the change left any subsystem's DESIGN.md
    describing something that is no longer true.

    Called automatically by the console once Apply succeeds — deliberately not
    a button the developer has to know to press, and deliberately a second call
    rather than part of `/apply`, so a slow or unreachable model can never delay
    or fail the apply beat itself.

    Returns `checked: false` (never a 5xx) when the review could not run. A doc
    that needs updating comes back with its own `proposal_id`, which the
    existing `/apply` endpoint applies like any other proposal.
    """
    target = targets.get_target(payload.target_id)
    result = review_after_apply(
        payload.applied_files, proposal_id=payload.proposal_id, target=target
    )

    if payload.ticket_number:
        for finding in result.stale_docs:
            record_event(
                payload.ticket_number,
                "ai",
                "design_doc_update_suggested",
                detail=f"{finding.design_doc}: {finding.reason}",
            )

    return {
        "label": AI_SUGGESTION_LABEL,
        "checked": result.checked,
        "unavailable_reason": result.unavailable_reason,
        "affected_subsystems": [
            {
                "subsystem": impact.subsystem,
                "design_doc": impact.design_doc,
                "applied_files": list(impact.applied_files),
            }
            for impact in result.impacts
        ],
        "findings": [
            {
                "subsystem": finding.subsystem,
                "design_doc": finding.design_doc,
                "applied_files": list(finding.applied_files),
                "still_accurate": finding.still_accurate,
                "reason": finding.reason,
                "proposal_id": finding.proposal_id,
                "diff_text": finding.diff_text,
            }
            for finding in result.findings
        ],
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
    namespace: str = targets.MOCKAPP_AMENDMENT_FIELD_ADD.cache_namespace,
    identity: Identity = Depends(require_identity),
) -> dict:
    """Base64-encoded before/after PNG for the amendment-form demo beat
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


# Resolutions already computed in this process, keyed by user story identifier and a
# digest of the user story's text so editing a user story re-resolves it. Belt to the
# ticket-events log's braces: the log makes the resolve a once-ever cost, and
# this makes it a once-ever cost even for the burst of board polls that can
# arrive before the first record lands.
_STORY_TARGET_MEMO: dict[str, TargetMatch] = {}


def _story_target_match(ticket: story_intake.StoryTicket) -> TargetMatch:
    """Resolve one user story to a registered target, at most once per user story revision.

    `resolve_target_for_story`'s third tier is an LLM call (US-2026-044 is the
    user story that lands there), and the board is polled — so this must never run
    per request. Only ever called on a user story's *first* sighting; every board
    load after that reads the answer back out of the ticket-events log via
    `_story_link_fields`.
    """
    memo_key = f"{ticket.story_id}:{hashlib.sha256(ticket.text.encode('utf-8')).hexdigest()[:16]}"
    match = _STORY_TARGET_MEMO.get(memo_key)
    if match is None:
        match = resolve_target_for_story(ticket.text)
        _STORY_TARGET_MEMO[memo_key] = match
    return match


def _detail_value(value: str) -> str:
    """`k=v;k=v` details are parsed by splitting on those two characters, so
    a value carrying either would silently corrupt every field after it."""
    return value.replace(";", ",").replace("=", "-")


def _record_story_ticket(ticket: story_intake.StoryTicket) -> None:
    """First sighting of a user story file: resolve its target once and write the
    ticket into the same append-only log the cross-team and problem-record
    tickets use. `record_event` is idempotent per (key, actor, action,
    detail), so this is safe to reach twice; the `_story_link_fields` guard
    above it is what stops the *resolve* from running twice."""
    match = _story_target_match(ticket)
    detail = f"story_file={_detail_value(ticket.story_file)}"
    if match.resolved and match.target is not None:
        detail += (
            f";target_id={_detail_value(match.target.target_id)}"
            f";target_display_name={_detail_value(match.target.display_name)}"
            f";target_method={_detail_value(match.method)}"
        )
    record_event(ticket.key, "system", story_intake.TICKET_CREATED_ACTION, detail=detail)
    if match.resolved and match.target is not None:
        record_event(
            ticket.key,
            "system",
            "target_resolved",
            detail=f"{match.target.display_name} via {match.method}",
        )


def _story_board_rows(issues: list[dict], project_key: str) -> list[dict]:
    """Board rows for every user story under `stories/` that no existing ticket covers.

    The third intake source, alongside the recorded Jira search and the
    ticket-events log. "Covered" is read out of the tickets already on the
    board — a user story identifier in their summary or description (see
    `story_intake.story_ids_on_issue`) — so the four seeded demo user stories keep their
    hand-seeded keys (AMS-101..104) and are never duplicated, and nothing
    here renumbers or disturbs them.

    The row is derived rather than created through `JiraClient.create_issue`,
    for two reasons. The key stays a pure function of the user story identifier in
    every mode (create_issue mints its own key, in the AMS-100..999 band the
    seeded tickets already occupy), and a GET that a polling board issues
    every few seconds does not write to the Jira store. Everything that makes
    it a real ticket downstream — the timeline, the manager's Assign control,
    the status transitions — reads the ticket-events log and the per-issue
    cache, both of which this feeds.
    """
    covered_ids: set[str] = set()
    for issue in issues:
        covered_ids |= story_intake.story_ids_on_issue(issue)
    existing_keys = {issue.get("key") for issue in issues}

    rows: list[dict] = []
    for ticket in story_intake.all_story_tickets(project_key):
        if ticket.story_id in covered_ids or ticket.key in existing_keys:
            continue
        if not _story_link_fields(ticket.key):
            try:
                _record_story_ticket(ticket)
            except Exception:  # noqa: BLE001 - see below
                # A user story that cannot be resolved (or recorded) still belongs on
                # the board — the manager assigning it is the recovery path,
                # and a resolver that throws must not take the whole board
                # down with it. `_match_by_ai` already degrades an LLMError to
                # "unresolved" on its own; this is the backstop for everything
                # else, including a read-only events log.
                pass
        rows.append(
            {
                "key": ticket.key,
                "id": ticket.key,
                "self": None,
                "summary": ticket.summary,
                "status": "To Do",
                # "Story", not "Task": the intake artifact these rows are built
                # from is a user story (business objective, target population,
                # Given/When/Then acceptance criteria), and the board is the
                # first thing the demo audience reads. The *release* document at
                # the end is the user story — see release.py.
                "issue_type": "Story",
                # Unassigned on purpose: an unassigned ticket is what puts the
                # user story in front of the manager, who already sees exactly those
                # on the dashboard with an Assign control. Nothing here picks
                # an engineer.
                "assignee": None,
                "description": ticket.description,
            }
        )
    return rows


@router.get("/jira/board")
def jira_board(identity: Identity = Depends(require_identity)) -> dict:
    """Compact issue list driving the engineer's Jira-styled board view.

    Three sources, merged. The seeded/recorded search result only ever
    reflects the fixed demo tickets (AMS-101/102/098) — it has no way to know
    about a cross-team or problem-record ticket created moments ago. Those
    are tracked instead via the ticket-events log (every creation records a
    `cross_team_ticket_created` or `problem_record_ticket_created` event on
    the new key), so this merges that list in — this is how an assignee
    logging in separately actually sees their new ticket on the shared board,
    not just via the dependency lookup. Third, every user story file under `stories/`
    that no ticket covers yet gets one opened for it (see `_story_board_rows`),
    so onboarding a change means dropping its user story in, not seeding a ticket by
    hand as well.
    """
    project_key = os.environ.get("JIRA_PROJECT_KEY", "AMS")
    client = get_jira_client()
    try:
        issues = client.search_issues(f"project = {project_key} ORDER BY updated DESC")
    except JiraError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    seen_keys = {issue.get("key") for issue in issues}
    created_keys = distinct_tickets_with_action(
        "cross_team_ticket_created"
    ) | distinct_tickets_with_action("problem_record_ticket_created")
    for key in sorted(created_keys - seen_keys):
        try:
            issues.append(client.get_issue(key))
        except JiraError:
            continue

    issues.extend(_story_board_rows(issues, project_key))

    # Overlay each issue's current status/assignee from the per-issue cache:
    # the seeded search recording is static, but assign/status changes made
    # during a session (analysis started -> In Progress, QA handoff) update
    # the get_issue cache — without this merge the board would show stale
    # columns after any workflow transition. Origin/problem_id (see
    # _origin_fields) and the user story link (see _story_link_fields) are likewise
    # derived fresh every call, not stored on the issue itself, so they stay
    # correct even for a ticket created in an earlier session.
    merged = []
    for issue in issues:
        key = issue.get("key")
        try:
            fresh = client.get_issue(str(key))
        except JiraError:
            merged.append({**issue, **_origin_fields(str(key)), **_story_link_fields(str(key))})
            continue
        overlay = {k: v for k, v in fresh.items() if v is not None}
        # An explicitly null assignee is a real value, not a missing one:
        # unassigning a ticket back to the manager's queue has to beat the
        # static search recording's stale assignee, which the filter above
        # would otherwise let win.
        if "assignee" in fresh:
            overlay["assignee"] = fresh["assignee"]
        merged.append(
            {
                **issue,
                **overlay,
                **_origin_fields(str(key)),
                **_story_link_fields(str(key)),
            }
        )

    return {"project_key": project_key, "issues": merged}


@router.post("/tests/scenarios")
def tests_scenarios(payload: TierRequest, identity: Identity = Depends(require_identity)) -> dict:
    """Draft the test plan — scenarios traced to the user story's acceptance criteria,
    before any test code exists. Produces a document, never a file on disk."""
    target = targets.get_target(payload.target_id)
    story_text = _story_text_or_400(payload.tier_name, target=target)
    try:
        draft = draft_scenarios(story_text, target=target)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if payload.ticket_number:
        record_event(
            payload.ticket_number,
            "ai",
            "test_scenarios_drafted",
            detail=f"{len(draft.scenarios)} scenarios across {len(draft.criteria)} criteria",
        )
    return {
        "label": AI_SUGGESTION_LABEL,
        "scenarios": [scenario.to_dict() for scenario in draft.scenarios],
        "criteria": [
            {"id": c.id, "text": c.text, "is_regression": c.is_regression}
            for c in draft.criteria
        ],
        "uncovered_criteria": draft.uncovered_criteria,
        "token_panel": {
            "scoped_input_tokens": draft.scoped_input_tokens,
            "scoped_output_tokens": draft.scoped_output_tokens,
            "estimated": draft.tokens_estimated,
        },
    }


@router.post("/tests/scenarios/approve")
def tests_scenarios_approve(
    payload: ScenarioApprovalRequest, identity: Identity = Depends(require_identity)
) -> dict:
    """Validate a tester-edited scenario list and record the approval.

    The console could keep the edited plan to itself, but then "the tester
    approved this" would be a client-side claim with no audit trail. Running
    the edited list back through the same validator the draft passed also
    means an edit can't smuggle in an untraceable scenario.
    """
    target = targets.get_target(payload.target_id)
    story_text = _story_text_or_400(payload.tier_name, target=target)
    criteria = parse_acceptance_criteria(story_text)
    scenarios = resolve_criteria_refs(
        [scenario_from_dict(raw) for raw in payload.scenarios], criteria
    )
    try:
        validate_scenarios(scenarios, criteria)
    except LLMError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    gaps = uncovered_criteria(scenarios, criteria)
    if payload.ticket_number:
        detail = f"{len(scenarios)} scenarios approved by {identity.name}"
        if gaps:
            detail += f"; no scenario covers {', '.join(gaps)}"
        record_event(payload.ticket_number, "human", "test_scenarios_approved", detail=detail)
    return {
        "scenarios": [scenario.to_dict() for scenario in scenarios],
        "uncovered_criteria": gaps,
        "approved_by": identity.name,
    }


@router.post("/tests/generate")
def tests_generate(
    payload: TestsGenerateRequest, identity: Identity = Depends(require_identity)
) -> dict:
    """Generate (and stage into the working tree) the target's test file only
    — nothing runs yet. The tester reviews the diff, then hits /tests/run.

    `scenarios` carries the tester-approved plan into the prompt so the
    generated suite is written against the reviewed list rather than against
    the user story alone. In replay mode the recorded suite is served regardless (as
    with every other AI beat here) — the console says so rather than implying
    an edit re-drove the generation.
    """
    target = targets.get_target(payload.target_id)
    story_text = _story_text_or_400(payload.tier_name, target=target)
    try:
        result = generate_tests(
            payload.tier_name, story_text, target=target, scenarios=payload.scenarios or None
        )
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


def _test_case_from_dict(raw: dict) -> testrun.TestCase:
    return testrun.TestCase(
        name=str(raw.get("name", "")),
        classname=str(raw.get("classname", "")),
        description=str(raw.get("description", "")),
        status=str(raw.get("status", "passed")),
        time_s=float(raw.get("time_s") or 0.0),
        message=raw.get("message"),
    )


@router.post("/tests/traceability")
def tests_traceability(
    payload: TraceabilityRequest, identity: Identity = Depends(require_identity)
) -> dict:
    """Acceptance criterion -> scenario -> automated test -> result.

    The criteria come from the user story, the citations from the approved plan, and
    the results from the two runs. Only the scenario-to-test link is inferred,
    conservatively — see s3_enhancement/traceability.py on why an unmatched
    row is the safe answer and a wrongly matched one is not.
    """
    target = targets.get_target(payload.target_id)
    story_text = _story_text_or_400(payload.tier_name, target=target)
    criteria = parse_acceptance_criteria(story_text)
    if not criteria:
        raise HTTPException(
            status_code=409,
            detail="This user story states no acceptance criteria, so there is nothing to trace to.",
        )

    matrix = build_matrix(
        criteria,
        [scenario_from_dict(raw) for raw in payload.scenarios],
        generated_cases=[_test_case_from_dict(raw) for raw in payload.generated_cases],
        regression_cases=[_test_case_from_dict(raw) for raw in payload.regression_cases],
    )

    if payload.ticket_number:
        counts = matrix.summary()
        gaps = counts["not_automated"] + counts["no_scenario"]
        record_event(
            payload.ticket_number,
            "system",
            "traceability_built",
            detail=(
                f"{counts['passed']}/{counts['total']} acceptance criteria evidenced"
                + (f"; {gaps} with no automated coverage" if gaps else "")
            ),
        )
    return matrix.to_dict()


@router.post("/tests/regression")
def tests_regression(payload: TierRequest, identity: Identity = Depends(require_identity)) -> dict:
    """Run the target app's checked-in, pre-existing regression suite.

    Separate endpoint, separate result, deliberately: the generated suite
    proves the user story does what it said, and this proves it didn't cost anything
    that already worked. Runnable at any point — it needs neither generated
    code nor generated tests — so a presenter can take a green baseline
    before Apply and re-run it after.
    """
    target = targets.get_target(payload.target_id)
    try:
        run = testrun.run_regression(target)
    except testrun.NoRegressionSuiteError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except testrun.TestRunnerNotFoundError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if payload.ticket_number:
        summary = run.summary()
        record_event(
            payload.ticket_number,
            "system",
            "regression_passed" if run.passed else "regression_failed",
            detail=f"{summary['passed']}/{summary['total']} pre-existing tests passed",
        )
    return {
        "suite_paths": list(target.regression_paths or target.regression_command),
        **_suite_run_dict(run),
    }


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
    story_text = _story_text_or_400(payload.tier_name, target=target)
    try:
        result = generate_tests(payload.tier_name, story_text, target=target)
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


def _story_label_for(target: Target) -> str:
    """The user story's identifier as the document should title it. Read off the
    template filename so the server never depends on the console telling it
    which user story it is currently showing."""
    if target.story_template_path is not None:
        return target.story_template_path.stem
    return target.display_name


@router.post("/design-doc")
def design_doc(
    payload: DesignDocRequest, identity: Identity = Depends(require_identity)
) -> dict:
    """Draft the internal design doc that hands the applied change off to QA
    — the artifact test generation is written against, sitting between
    "apply" and "generate tests" in the pipeline.

    The change map ships with it. It costs no model call (see
    s3_enhancement/diagram.py), so it is built unconditionally rather than
    hidden behind another button.
    """
    target = targets.get_target(payload.target_id)
    story_text = _story_text_or_400(payload.tier_name, target=target)
    try:
        text = draft_design_doc(story_text, target=target)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    diagram_svg, change_map = build_svg(target, downstream=payload.downstream_apps)

    if payload.ticket_number:
        record_event(payload.ticket_number, "ai", "design_doc_drafted", detail="")
    return {
        "label": AI_SUGGESTION_LABEL,
        "design_doc": text,
        "diagram_svg": diagram_svg,
        "diagram_caption": caption_for(change_map),
        "changed_files": [node.rel_path for node in change_map.nodes],
    }


@router.post("/design-doc/document")
def design_doc_document(
    payload: DesignDocExportRequest, identity: Identity = Depends(require_identity)
) -> Response:
    """The design doc as a downloadable file — HTML or PDF, same renderer.

    Deliberately re-drafts server-side rather than accepting document text
    from the browser: the draft is cache-pinned so this is free and returns
    the identical document, and it keeps a rendering endpoint from being
    handed arbitrary markup to render.
    """
    target = targets.get_target(payload.target_id)
    story_text = _story_text_or_400(payload.tier_name, target=target)
    try:
        text = draft_design_doc(story_text, target=target)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    story_label = _story_label_for(target)
    diagram_svg, change_map = build_svg(target, downstream=payload.downstream_apps)
    html = render_document_html(
        text,
        story_label=story_label,
        ticket_key=payload.ticket_number or "unassigned",
        diagram_svg=diagram_svg if payload.include_diagram else None,
        diagram_caption=caption_for(change_map),
    )

    if payload.format == "html":
        return Response(
            content=html,
            media_type="text/html; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{story_label}-design-doc.html"'
            },
        )

    try:
        pdf = render_pdf(html)
    except PdfUnavailableError as exc:
        # 503, not 500: the request is fine and the caller has a working
        # alternative (the browser's own print-to-PDF), which the console
        # falls back to on exactly this status.
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if payload.ticket_number:
        record_event(
            payload.ticket_number,
            "human",
            "design_doc_exported",
            detail=f"PDF downloaded by {identity.name}",
        )
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{story_label}-design-doc.pdf"'
        },
    )


def _release_context(payload, identity: Identity):
    """Everything the release beats share: target, user story text, change map, plan."""
    target = targets.get_target(payload.target_id)
    story_text = _story_text_or_400(payload.tier_name, target=target)
    change_map = build_change_map(target, downstream=payload.downstream_apps)
    proposal_id = getattr(payload, "proposal_id", None)
    branch = scm.state_for(proposal_id) if proposal_id else None
    plan = build_deployment_plan(
        target,
        change_map,
        applied_files=getattr(payload, "applied_files", None) or None,
        branch=branch,
    )
    return target, story_text, change_map, plan, branch


def _evidence_from(payload: ReleaseRecordRequest) -> list[SuiteEvidence]:
    """Turn the console's raw run results into the record's headline rows.

    A suite that was never run is absent rather than reported as zero-passed:
    "not run" and "ran and found nothing" are different claims, and
    `unproven_claims` treats the absence as a gap.
    """
    evidence: list[SuiteEvidence] = []
    if payload.generated_cases:
        passed = sum(1 for case in payload.generated_cases if case.get("status") == "passed")
        evidence.append(
            SuiteEvidence(
                name="Generated suite",
                passed=passed == len(payload.generated_cases),
                total=len(payload.generated_cases),
                passed_count=passed,
                note="written for this change",
            )
        )
    if payload.regression_cases:
        passed = sum(1 for case in payload.regression_cases if case.get("status") == "passed")
        evidence.append(
            SuiteEvidence(
                name="Regression (pre-existing)",
                passed=passed == len(payload.regression_cases),
                total=len(payload.regression_cases),
                passed_count=passed,
                note="checked in before this user story; the pipeline cannot write to it",
            )
        )
    if payload.mutation:
        caught = bool(payload.mutation.get("caught"))
        total = int(payload.mutation.get("total") or 0)
        failed = int(payload.mutation.get("failed") or 0)
        evidence.append(
            SuiteEvidence(
                name="Seeded-bug check",
                passed=caught,
                total=total,
                passed_count=max(0, total - failed),
                note=(
                    f"{failed} test(s) went red against an injected bug, as intended"
                    if caught
                    else "the suite did NOT catch the injected bug"
                ),
            )
        )
    return evidence


@router.post("/release/notes")
def release_note_set(
    payload: ReleaseRequest, identity: Identity = Depends(require_identity)
) -> dict:
    """The three audience-specific release notes, plus the derived deployment
    plan. One call because the plan costs nothing — it is computed from the
    change's own file set, not drafted."""
    target, story_text, change_map, plan, _branch = _release_context(payload, identity)
    usage: dict = {}
    try:
        notes = draft_release_note_set(story_text, target=target, usage_out=usage)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if payload.ticket_number:
        record_event(payload.ticket_number, "ai", "release_notes_drafted", detail="")
    return {
        "label": AI_SUGGESTION_LABEL,
        "notes": notes.to_dict(),
        "plan": plan.to_dict(),
        "token_panel": {
            "scoped_input_tokens": usage.get("input_tokens"),
            "scoped_output_tokens": usage.get("output_tokens"),
            "estimated": bool(usage.get("estimated")),
        },
    }


def _build_record(
    payload: ReleaseRecordRequest, identity: Identity
) -> tuple[ReleaseRecord, str]:
    target, story_text, change_map, plan, branch = _release_context(payload, identity)
    criteria = parse_acceptance_criteria(story_text)
    matrix = (
        build_matrix(
            criteria,
            [scenario_from_dict(raw) for raw in payload.scenarios],
            generated_cases=[_test_case_from_dict(raw) for raw in payload.generated_cases],
            regression_cases=[_test_case_from_dict(raw) for raw in payload.regression_cases],
        )
        if criteria
        else None
    )
    evidence = _evidence_from(payload)
    try:
        notes = draft_release_note_set(story_text, target=target)
    except LLMError:
        # The record's value is the evidence, not the prose. A model that is
        # unreachable at release time must not stop the artifact being
        # produced — it just ships without the notes section.
        notes = None

    diagram_svg, _ = build_svg(target, downstream=payload.downstream_apps)
    record = ReleaseRecord(
        story_label=_story_label_for(target),
        ticket_key=payload.ticket_number or "unassigned",
        released_by=identity.name,
        generated_at=datetime.now(),
        changed_files=payload.applied_files or [node.rel_path for node in change_map.nodes],
        criteria=criteria,
        matrix=matrix,
        evidence=evidence,
        approvals=collect_approvals(
            events_for(payload.ticket_number) if payload.ticket_number else []
        ),
        plan=plan,
        notes=notes,
        diagram_svg=diagram_svg,
        diagram_caption=caption_for(change_map),
        unproven=unproven_claims(matrix, evidence, branch),
        branch=branch,
    )
    return record, render_release_record_html(record)


@router.post("/release/record")
def release_record(
    payload: ReleaseRecordRequest, identity: Identity = Depends(require_identity)
) -> Response:
    """The release record as a downloadable file."""
    record, html = _build_record(payload, identity)
    filename = f"{record.story_label}-release-record"

    if payload.format == "html":
        return Response(
            content=html,
            media_type="text/html; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}.html"'},
        )
    try:
        pdf = render_pdf(html)
    except PdfUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}.pdf"'},
    )


@router.post("/release/attach")
def release_record_attach(
    payload: ReleaseRecordRequest, identity: Identity = Depends(require_identity)
) -> dict:
    """Attach the release record to its Jira ticket.

    Honest about the demo default: with JIRA_MODE=replay there is no Jira to
    attach to, and `attach_file`'s replay cache is keyed partly by content
    digest, which a freshly rendered PDF can never match. Rather than fake a
    recording, the beat records the intent against the ticket timeline and
    reports the attachment as simulated — the same convention the "Check out
    repo" beat uses for an operation it does not really perform.
    """
    if not payload.ticket_number:
        raise HTTPException(status_code=422, detail="A ticket number is required to attach.")

    record, html = _build_record(payload, identity)
    try:
        pdf = render_pdf(html)
    except PdfUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    filename = f"{record.story_label}-release-record.pdf"

    mode = os.environ.get("JIRA_MODE", "replay").lower()
    if mode == "replay":
        record_event(
            payload.ticket_number,
            "human",
            "release_record_attached",
            detail=f"{filename} prepared by {identity.name} (simulated — JIRA_MODE=replay)",
        )
        return {
            "attached": False,
            "simulated": True,
            "filename": filename,
            "size_bytes": len(pdf),
            "detail": (
                "Recorded against the ticket. The attachment itself is simulated because "
                "this console is running with JIRA_MODE=replay; set JIRA_MODE=live to "
                "upload it to the real ticket."
            ),
        }

    try:
        get_jira_client().attach_file(
            payload.ticket_number, filename, pdf, "application/pdf"
        )
    except JiraError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    record_event(
        payload.ticket_number,
        "human",
        "release_record_attached",
        detail=f"{filename} attached by {identity.name}",
    )
    return {
        "attached": True,
        "simulated": False,
        "filename": filename,
        "size_bytes": len(pdf),
        "detail": f"{filename} attached to {payload.ticket_number}.",
    }


@router.post("/release-notes")
def release_notes(payload: TierRequest, identity: Identity = Depends(require_identity)) -> dict:
    target = targets.get_target(payload.target_id)
    story_text = _story_text_or_400(payload.tier_name, target=target)
    try:
        text = draft_release_notes(story_text, target=target)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"label": AI_SUGGESTION_LABEL, "release_notes": text}


@router.get("/harness/latest")
def harness_latest(identity: Identity = Depends(require_identity)) -> dict:
    run_dir = latest_harness_run()
    if run_dir is None or not (run_dir / "status.json").exists():
        raise HTTPException(
            status_code=404,
            detail="No harness run found yet — run the harness script first.",
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
    story_text = _story_text_or_400(payload.tier_name)
    try:
        repo_size = len(get_client().list_repo_paths(project_id))
        gitlab_files = discover_gitlab_files(project_id, story_text)
        selection = select_relevant_files(story_text, gitlab_files, core_files=(), design_docs={})
    except GitLabError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {
        "repo_size": repo_size,
        "files_reached_llm": len(selection.selected),
        "selected_files": list(selection.selected.keys()),
    }


class GitlabScopeAutoRequest(BaseModel):
    # Exactly one of these carries the user story text: `tier_name` for one of the
    # console's pinned user story templates (see TierRequest elsewhere in this
    # file), or `story_text` for a ticket with no tier/target linked in this
    # console (e.g. a cross-team ticket) — same free-text shape
    # AdhocAnalyzeRequest already uses for /analyze-adhoc, since those
    # ad-hoc tickets are exactly the case where the caller doesn't already
    # know which repo the user story belongs to.
    tier_name: str | None = None
    story_text: str | None = None
    target_id: str | None = None
    ticket_number: str | None = None
    # Set once the developer has confirmed (or overridden) an uncertain
    # repo-match from a prior needs_clarification response below — skips the
    # confidence gate and scopes directly against this project_id instead of
    # asking again.
    confirmed_project_id: str | None = None


@router.post("/gitlab/scope-auto")
def gitlab_scope_auto(
    payload: GitlabScopeAutoRequest, identity: Identity = Depends(require_identity)
) -> dict:
    """Same as /gitlab/projects/{id}/scope, but for when the caller doesn't know
    which repo the user story belongs to — an AI pick over the project list stands in for
    the manual project_id above, labeled like every other AI suggestion.

    A repo-match below 'high' confidence is not scoped against silently: it
    comes back as `needs_clarification` (same contract as /analyze-adhoc and
    /chat/quick-impact) asking the developer "is this the current repo?"
    before file discovery runs against a possibly-wrong project. Resubmit
    with `confirmed_project_id` set to skip straight to scoping.
    """
    if payload.story_text is not None:
        story_text = payload.story_text.strip()
        if not story_text:
            raise HTTPException(status_code=422, detail="story_text must not be empty")
        if len(story_text) > 4000:
            raise HTTPException(
                status_code=422, detail="story_text is too long (max 4000 characters)"
            )
    elif payload.tier_name:
        story_text = _story_text_or_400(payload.tier_name)
    else:
        raise HTTPException(status_code=422, detail="either tier_name or story_text is required")

    try:
        projects = get_client().list_projects()
        if payload.confirmed_project_id:
            best_match = RepoMatch(
                project_id=payload.confirmed_project_id,
                confidence="confirmed",
                reasoning="developer-confirmed",
            )
            alternates: tuple[RepoMatch, ...] = ()
        else:
            suggestion = suggest_target_repo(story_text, projects)
            if needs_confirmation(suggestion.best_match):
                if payload.ticket_number:
                    record_event(
                        payload.ticket_number,
                        "ai",
                        "repo_match_confirmation_requested",
                        detail=f"{suggestion.best_match.project_id} "
                        f"({suggestion.best_match.confidence})",
                    )
                return {
                    "label": AI_SUGGESTION_LABEL,
                    "needs_clarification": True,
                    "question": build_confirmation_question(suggestion, projects),
                    "suggested_project": _describe_repo_match(suggestion.best_match, projects),
                    "alternates": [
                        _describe_repo_match(alt, projects) for alt in suggestion.alternates
                    ],
                }
            best_match = suggestion.best_match
            alternates = suggestion.alternates

        project_id = best_match.project_id
        repo_size = len(get_client().list_repo_paths(project_id))
        gitlab_files = discover_gitlab_files(project_id, story_text)
        selection = select_relevant_files(story_text, gitlab_files, core_files=(), design_docs={})
    except GitLabError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {
        "label": AI_SUGGESTION_LABEL,
        "needs_clarification": False,
        "suggested_project": _describe_repo_match(best_match, projects),
        "alternates": [_describe_repo_match(alt, projects) for alt in alternates],
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
        response["suggested_story_summary"] = result.suggested_story_summary
    return response
