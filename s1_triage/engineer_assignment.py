"""S1 — individual engineer assignment within a routed assignment_group.

Extends `routing.py`'s group-level routing with a second, workload-and-
complexity-aware pick of *which engineer in that group* gets the ticket.
Deterministic — no LLM call, same reliability posture as `routing.py` itself.

No schema/CSV change: which tickets are "assigned" to which engineer is
tracked the same way `queue_status.py` already derives live ticket state —
as events in `common/ticket_events.py` — so `demo/reset_s1.sh` (which already
clears the event log) resets this for free, and bandwidth builds up naturally
as a presenter runs Auto-draft/Batch mode live.
"""

from __future__ import annotations

from dataclasses import dataclass

from common.constants import ASSIGNMENT_GROUPS
from common.schema import Incident
from common.ticket_events import (
    distinct_tickets_with_action,
    events_for,
    tickets_with_action_detail,
)
from s1_triage.routing import RoutingResult

ENGINEER_ASSIGNED_ACTION = "engineer_assigned"

# Fictional roster only (CLAUDE.md hard rule #2) — two engineers per assignment
# group so any incident an presenter selects resolves to a real roster.
ENGINEERS_BY_GROUP: dict[str, list[str]] = {
    "App Support — PolicyCore": ["Ravi Kumar", "Elena Cruz"],
    "App Support — ClaimsPortal": ["Priya Nair", "Tom Becker"],
    "App Support — BillingGateway": ["Sam Patel", "Grace Liu"],
    "App Support — DocumentHub": ["Noah Bennett", "Aisha Khan"],
    "Batch Ops": ["Jordan Blake", "Meera Iyer"],
    "Integration Support": ["Diego Ramos", "Hana Suzuki"],
    "Service Desk L1": ["Alex Morgan", "Priti Rao"],
}
assert set(ENGINEERS_BY_GROUP) == set(ASSIGNMENT_GROUPS)

PRIORITY_WEIGHT = {"P1": 4, "P2": 3, "P3": 2, "P4": 1}


def complexity_score(incident: Incident) -> int:
    """A ticket's weighted load, not just "one ticket": priority (impact) plus
    reassignment_count (an existing schema field — tickets that already
    bounced between groups are demonstrably harder), so an engineer holding
    fewer but gnarlier tickets isn't read as having spare bandwidth."""
    return PRIORITY_WEIGHT.get(incident.priority, 2) + incident.reassignment_count


def _open_tickets_for(engineer: str) -> set[str]:
    assigned = tickets_with_action_detail(ENGINEER_ASSIGNED_ACTION, engineer)
    resolved = distinct_tickets_with_action("resolved")
    return assigned - resolved


def open_incidents_for(engineer: str, all_incidents: list[Incident]) -> list[Incident]:
    open_numbers = _open_tickets_for(engineer)
    return [incident for incident in all_incidents if incident.number in open_numbers]


def current_bandwidth(engineer: str, all_incidents: list[Incident]) -> int:
    open_incidents = open_incidents_for(engineer, all_incidents)
    return sum(complexity_score(incident) for incident in open_incidents)


@dataclass(frozen=True)
class EngineerAssignment:
    engineer: str
    bandwidth_before: int
    citation: str


def assign_engineer(
    incident: Incident,
    routing_result: RoutingResult,
    all_incidents: list[Incident],
) -> EngineerAssignment:
    roster = ENGINEERS_BY_GROUP.get(routing_result.assignment_group, [])
    if not roster:
        return EngineerAssignment(
            engineer="Unassigned",
            bandwidth_before=0,
            citation=f"No engineer roster configured for {routing_result.assignment_group!r}.",
        )

    loads = {name: current_bandwidth(name, all_incidents) for name in roster}
    # Deterministic tie-break by name so a repeat run with identical ticket_events
    # history always picks the same engineer.
    chosen = min(roster, key=lambda name: (loads[name], name))

    incoming = complexity_score(incident)
    peers = ", ".join(f"{name}: {loads[name]}" for name in roster if name != chosen)
    reassign_note = (
        f", {incident.reassignment_count} prior reassignment(s)"
        if incident.reassignment_count
        else ""
    )
    citation = (
        f"{chosen} selected — current weighted bandwidth {loads[chosen]}"
        + (f" (peers — {peers})" if peers else "")
        + f"; this ticket adds {incoming} (priority {incident.priority}{reassign_note})."
    )
    return EngineerAssignment(engineer=chosen, bandwidth_before=loads[chosen], citation=citation)


def assigned_engineer_for(ticket_number: str) -> str | None:
    """Who a ticket is already assigned to, straight from its own event log —
    never re-decided. Assignment happens exactly once (the background pass in
    `batch.py`); every later view (My Queue's list, its per-ticket drill-down)
    must read that decision rather than calling `assign_engineer()` again,
    since bandwidth shifts over time and a second call could pick someone
    else, leaving a ticket double-booked across two engineers' queues."""
    for event in events_for(ticket_number):
        if event.get("action") == ENGINEER_ASSIGNED_ACTION:
            return event.get("detail") or None
    return None


def team_bandwidth(group: str, all_incidents: list[Incident]) -> list[tuple[str, int, int]]:
    """(engineer, open ticket count, weighted bandwidth) for every roster member
    in `group`, for the My Queue peer-comparison table."""
    return [
        (name, len(open_incidents_for(name, all_incidents)), current_bandwidth(name, all_incidents))
        for name in ENGINEERS_BY_GROUP.get(group, [])
    ]


def group_for_engineer(engineer: str) -> str | None:
    for group, roster in ENGINEERS_BY_GROUP.items():
        if engineer in roster:
            return group
    return None
