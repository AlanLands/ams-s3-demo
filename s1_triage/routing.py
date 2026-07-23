"""S1 capability 1.2 — deterministic assignment-group routing."""

from __future__ import annotations

from dataclasses import dataclass

from common.constants import ASSIGNMENT_GROUPS
from common.schema import Incident
from s1_triage.data_access import load_incidents
from s1_triage.triage import TriageResult

APP_TO_GROUP = {
    "PolicyCore": "App Support — PolicyCore",
    "ClaimsPortal": "App Support — ClaimsPortal",
    "BillingGateway": "App Support — BillingGateway",
    "DocumentHub": "App Support — DocumentHub",
    "NightlyBatch": "Batch Ops",
    "IntegrationBridge": "Integration Support",
}


@dataclass(frozen=True)
class RoutingResult:
    assignment_group: str
    citation: str


def _precedent_count(incident: Incident, assignment_group: str) -> int:
    # Scoped by category, not just application: application alone maps 1:1 to
    # assignment_group (see APP_TO_GROUP), so an application-only count is the same
    # number for every incident of that app regardless of what it's actually about —
    # it would look like per-incident reasoning while really just being app volume.
    return sum(
        1
        for prior in load_incidents()
        if prior.number != incident.number
        and prior.application == incident.application
        and prior.category == incident.category
        and prior.assignment_group == assignment_group
        and prior.resolution_notes
    )


def route(incident: Incident, triage_result: TriageResult) -> RoutingResult:
    assignment_group = APP_TO_GROUP.get(incident.application, "Service Desk L1")
    if assignment_group not in ASSIGNMENT_GROUPS:
        assignment_group = "Service Desk L1"

    count = _precedent_count(incident, assignment_group)
    citation_bits = [
        f"Application {incident.application} maps to {assignment_group}",
        f"similar to {count} prior resolved {incident.application}/{incident.category} "
        "incidents routed there",
        f"Final triage: {triage_result.final_category} / {triage_result.final_priority}",
    ]
    if triage_result.rule_match:
        citation_bits.append(f"rule cited: {triage_result.rule_match.rule_name}")
    return RoutingResult(
        assignment_group=assignment_group,
        citation="; ".join(citation_bits) + ".",
    )
