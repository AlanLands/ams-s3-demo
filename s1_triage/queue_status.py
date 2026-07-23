"""Per-incident live queue status.

Distinct from `s1_triage.funnel.FunnelStage`: that's a pre-pipeline forecast
("would this need a human to classify?"), computed with zero LLM calls or
session state, for every incident whether or not anyone has opened it.
QueueStatus is the ground truth for an incident that has actually been run
through the background pipeline / opened in My Queue this session — the live
event trail in common/ticket_events.py always overrides the forecast.
"""

from __future__ import annotations

from typing import Literal

from common.ticket_events import distinct_tickets_with_action
from s1_triage.funnel import FunnelStage

QueueStatus = Literal[
    "needs_human_review",
    "awaiting_engineer_approval",
    "info_requested",
    "ai_resolved",
]

QUEUE_STATUS_ORDER: list[QueueStatus] = [
    "needs_human_review",
    "awaiting_engineer_approval",
    "info_requested",
    "ai_resolved",
]

QUEUE_STATUS_LABELS: dict[QueueStatus, str] = {
    "needs_human_review": "Needs human review",
    "awaiting_engineer_approval": "Awaiting engineer approval",
    "info_requested": "Info requested from user",
    "ai_resolved": "AI-resolved (ticket updated)",
}


def queue_statuses(stage_by_number: dict[str, FunnelStage]) -> dict[str, QueueStatus]:
    """One status per incident number in `stage_by_number`.

    An incident with no recorded ticket events yet falls back to its forecast
    stage: `auto_triaged` reads as "awaiting engineer approval" (the AI
    pipeline would draft cleanly, it just hasn't been opened and approved
    yet); everything else reads as "needs human review".
    """
    resolved = distinct_tickets_with_action("resolved")
    info_requested = distinct_tickets_with_action("requestor_mail_auto_sent")
    drafted = distinct_tickets_with_action("resolution_draft")

    statuses: dict[str, QueueStatus] = {}
    for number, stage in stage_by_number.items():
        if number in resolved:
            statuses[number] = "ai_resolved"
        elif number in info_requested:
            statuses[number] = "info_requested"
        elif number in drafted:
            statuses[number] = "awaiting_engineer_approval"
        elif stage == "auto_triaged":
            statuses[number] = "awaiting_engineer_approval"
        else:
            statuses[number] = "needs_human_review"
    return statuses
