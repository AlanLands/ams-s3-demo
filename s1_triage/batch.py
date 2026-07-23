"""S1 batch-run: process every incident through the pipeline in one click.

Reuses the exact same per-incident logic Auto-draft mode uses (self-service
fast-path, else quality gate -> triage -> routing -> similar incidents ->
resolution draft), but headlessly -- no per-step Streamlit rendering, no
individual review UI. Ticket events are recorded exactly as Auto-draft mode
records them, so a ticket processed here shows up in the Triage Funnel's live
"Ticket queue status" view identically to one processed by hand. The caller
is responsible for computing the resulting queue status per incident (via
s1_triage.queue_status.queue_statuses(), same as the Triage Funnel table) --
this module only runs the pipeline and records events, it doesn't duplicate
that bucketing logic.
"""

from __future__ import annotations

from dataclasses import dataclass

from common.llm import LLMError
from common.schema import Incident
from common.ticket_events import Actor, record_event
from s1_triage.data_access import KbArticle
from s1_triage.engineer_assignment import assign_engineer, assigned_engineer_for
from s1_triage.quality_gate import assess
from s1_triage.resolution import draft_resolution
from s1_triage.routing import route
from s1_triage.self_service import match_self_service
from s1_triage.similar_incidents import find_similar
from s1_triage.triage import TriageResult, triage

# Batch runs headlessly, so it cannot pause for the arbitration the Auto-draft
# gate enforces; it proceeds on the AI verdict and flags rows for follow-up.
_AGREEMENT_NOTES: dict[str, str] = {
    "agree": "rule & AI agree",
    "deviation": "⚠ deviation from rule — review required",
    "ai_only": "⚠ AI-only, no rule fired — review required",
}


def _agreement_note(triage_result: TriageResult) -> str:
    return _AGREEMENT_NOTES[triage_result.agreement]


@dataclass(frozen=True)
class BatchResult:
    incident_number: str
    note: str


def _record(ticket_number: str, actor: Actor, action: str, detail: str = "") -> None:
    try:
        record_event(ticket_number, actor, action, detail)
    except OSError:
        pass


def run_one(
    incident: Incident, all_incidents: list[Incident], kb_articles: list[KbArticle]
) -> BatchResult:
    _record(
        incident.number,
        "system",
        "created",
        f"Incident opened in source data at {incident.opened_at}.",
    )

    self_service = match_self_service(incident)
    if self_service is not None:
        kind_text = self_service.kind.replace("_", " ")
        _record(
            incident.number,
            "system",
            "self_service_auto_resolved",
            f"Self-service {kind_text} matched — confirmation auto-sent, no engineer review.",
        )
        _record(
            incident.number,
            "system",
            "resolved",
            f"Ticket auto-resolved via self-service {kind_text}; closure stays with the client.",
        )
        return BatchResult(incident.number, f"Self-service {kind_text} — auto-resolved")

    try:
        verdict = assess(incident)
    except LLMError as exc:
        return BatchResult(incident.number, f"Pipeline unavailable ({exc})")

    verdict_detail = (
        f"{'investigable' if verdict.investigable else 'needs more info'} — {verdict.reasoning}"
    )
    _record(incident.number, "ai", "quality_gate", verdict_detail)

    if not verdict.investigable:
        if verdict.drafted_requestor_mail:
            _record(
                incident.number,
                "system",
                "requestor_mail_auto_sent",
                "Auto-sent info-request email to requestor (no engineer review).",
            )
            return BatchResult(incident.number, "Not investigable — info request auto-sent")
        return BatchResult(incident.number, "Not investigable — no mail drafted")

    try:
        triage_result = triage(incident)
        _record(
            incident.number,
            "ai",
            "triage",
            f"{triage_result.ai_priority} / {triage_result.ai_category} "
            f"({_agreement_note(triage_result)})",
        )
        routing_result = route(incident, triage_result)
        _record(incident.number, "ai", "routing", routing_result.assignment_group)
        # Assignment is once-per-ticket, ever: the background pass re-runs in
        # every new browser session (st.session_state doesn't survive them),
        # and record_event only dedups identical details — re-deciding here
        # against shifted bandwidths would append a second engineer_assigned
        # event with a different name, double-booking the ticket in two queues.
        engineer = assigned_engineer_for(incident.number)
        if engineer is None:
            engineer = assign_engineer(incident, routing_result, all_incidents).engineer
            _record(incident.number, "ai", "engineer_assigned", engineer)
        similar = find_similar(incident, all_incidents)
        _record(
            incident.number,
            "ai",
            "similar_incidents",
            f"{len(similar)} matching historical incident(s) surfaced.",
        )
        draft_resolution(incident, similar, kb_articles)
        _record(
            incident.number,
            "ai",
            "resolution_draft",
            "Drafted work note, resolution steps, and requestor email.",
        )
    except LLMError as exc:
        return BatchResult(incident.number, f"Pipeline unavailable ({exc})")

    return BatchResult(
        incident.number,
        f"Drafted — {triage_result.ai_priority} / {triage_result.ai_category} "
        f"({_agreement_note(triage_result)}) — assigned to {engineer}",
    )


def run_batch(
    incidents: list[Incident], all_incidents: list[Incident], kb_articles: list[KbArticle]
) -> list[BatchResult]:
    return [run_one(incident, all_incidents, kb_articles) for incident in incidents]
