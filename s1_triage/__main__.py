"""CLI smoke runner for the full S1 pipeline."""

from __future__ import annotations

import argparse

from common.constants import AI_SUGGESTION_LABEL
from s1_triage.data_access import load_incidents, load_kb_articles
from s1_triage.quality_gate import assess
from s1_triage.quality_gate import render as render_quality
from s1_triage.resolution import draft_resolution
from s1_triage.resolution import render as render_resolution
from s1_triage.routing import route
from s1_triage.similar_incidents import find_similar
from s1_triage.triage import triage


def main() -> None:
    parser = argparse.ArgumentParser(description="S1 full triage pipeline smoke runner")
    parser.add_argument("--row", type=int, default=0, help="0-indexed incident row")
    args = parser.parse_args()

    incidents = load_incidents()
    incident = incidents[args.row]

    print(f"Incident: {incident.number} - {incident.short_description}")
    print()
    print(f"--- {AI_SUGGESTION_LABEL} ---")
    print(render_quality(incident, assess(incident)))
    print()

    triage_result = triage(incident)
    print("Rule match:")
    print(triage_result.rule_match or "No editable application rule fired.")
    print()
    print(f"--- {AI_SUGGESTION_LABEL} ---")
    print(
        f"AI triage: {triage_result.ai_category} / {triage_result.ai_priority}\n"
        f"Reasoning: {triage_result.ai_reasoning}"
    )
    print()

    routing_result = route(incident, triage_result)
    print("Suggested assignment:")
    print(f"{routing_result.assignment_group} - {routing_result.citation}")
    print()

    similar = find_similar(incident, incidents)
    print("Similar incidents:")
    for item in similar:
        print(
            f"- {item.incident_number} score={item.similarity_score:.4f}: "
            f"{item.resolution_notes}"
        )
    print()

    draft = draft_resolution(incident, similar, load_kb_articles())
    print(render_resolution(draft))


if __name__ == "__main__":
    main()
