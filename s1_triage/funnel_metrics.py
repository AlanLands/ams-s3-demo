"""Pure metric computations for the S1 triage funnel view."""

from __future__ import annotations

from collections import Counter

from common.schema import Incident
from s1_triage.funnel import FunnelClassification, FunnelStage

STAGE_ORDER: list[FunnelStage] = ["auto_triaged", "needs_engineer_review", "needs_more_info"]


def funnel_counts(classifications: list[FunnelClassification]) -> dict[FunnelStage, int]:
    counts = Counter(item.stage for item in classifications)
    return {stage: counts.get(stage, 0) for stage in STAGE_ORDER}


def funnel_percentages(classifications: list[FunnelClassification]) -> dict[FunnelStage, float]:
    total = len(classifications)
    counts = funnel_counts(classifications)
    if total == 0:
        return {stage: 0.0 for stage in STAGE_ORDER}
    return {stage: round(count / total, 4) for stage, count in counts.items()}


def counts_by_application(
    classifications: list[FunnelClassification], incidents: list[Incident]
) -> dict[str, dict[FunnelStage, int]]:
    application_by_number = {incident.number: incident.application for incident in incidents}
    grouped: dict[str, Counter[FunnelStage]] = {}
    for item in classifications:
        application = application_by_number.get(item.incident_number, "Unknown")
        grouped.setdefault(application, Counter())[item.stage] += 1

    return {
        application: {stage: counts.get(stage, 0) for stage in STAGE_ORDER}
        for application, counts in sorted(grouped.items())
    }
