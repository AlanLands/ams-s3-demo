"""S1 triage funnel — deterministic "is a human needed?" classification.

Deliberately uses no LLM call: `rules_engine.apply_rules()` (S1 1.1) and
`similar_incidents.find_similar()` (S1 1.3, the Knowledge Repository — past-incident
precedent) are both already deterministic and already built. Classifying the whole
incident population via the LLM quality gate instead would mean hundreds of live LLM
calls on every dashboard load after `demo/reset_s1.sh` wipes `.cache/llm` — this stays
instant and free by design. The real LLM quality gate (1.0) is untouched; it still
runs per-incident in the background pipeline (`batch.py`) and My Queue's drill-down
exactly as before.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from common.schema import Incident
from s1_triage.rules_engine import apply_rules
from s1_triage.similar_incidents import find_similar

FunnelStage = Literal["auto_triaged", "needs_engineer_review", "needs_more_info"]

# Above similar_incidents.py's own 0.05 "is this even similar" floor — this is the
# higher bar for "confident enough to skip a human," not just "worth showing."
CONFIDENT_SIMILARITY_THRESHOLD = 0.15

# Real tickets in the seeded dataset run 25+ words; junk_quality_gate rows run 3-8.
# Checked empirically against data/incidents.csv, not guessed — see funnel plan notes.
# This has to come *before* the similarity check: background-noise incidents reuse a
# small set of templates verbatim, so almost every incident finds a "similar" match
# regardless of whether it actually has enough content to investigate. Similarity
# answers "have we seen this before?"; word count answers "is there anything here to
# match on?" — a thin ticket needs more info even if it happens to resemble another
# thin ticket.
THIN_TICKET_MAX_WORDS = 10


@dataclass(frozen=True)
class FunnelClassification:
    incident_number: str
    stage: FunnelStage
    rule_matched: bool
    best_similarity_score: float | None
    reasoning: str


def _word_count(incident: Incident) -> int:
    return len(f"{incident.short_description} {incident.description}".split())


def _reasoning(
    thin: bool, rule_matched: bool, rule_name: str | None, best_score: float | None
) -> str:
    if thin:
        return "Description too thin to match against — needs more detail from the requestor."
    rule_part = f"Rule '{rule_name}' matched" if rule_matched else "No rule matched"
    if best_score is None:
        kb_part = "no similar past incidents found"
    else:
        kb_part = f"top Knowledge Repository match score {best_score:.2f}"
    return f"{rule_part}; {kb_part}."


def classify(incident: Incident, all_incidents: list[Incident]) -> FunnelClassification:
    if _word_count(incident) <= THIN_TICKET_MAX_WORDS:
        return FunnelClassification(
            incident_number=incident.number,
            stage="needs_more_info",
            rule_matched=False,
            best_similarity_score=None,
            reasoning=_reasoning(True, False, None, None),
        )

    rule_match = apply_rules(incident)
    similar = find_similar(incident, all_incidents)
    best_score = similar[0].similarity_score if similar else None

    confident_match = best_score is not None and best_score >= CONFIDENT_SIMILARITY_THRESHOLD
    stage: FunnelStage = (
        "auto_triaged" if rule_match is not None and confident_match else "needs_engineer_review"
    )

    return FunnelClassification(
        incident_number=incident.number,
        stage=stage,
        rule_matched=rule_match is not None,
        best_similarity_score=best_score,
        reasoning=_reasoning(
            False, rule_match is not None, rule_match.rule_name if rule_match else None, best_score
        ),
    )


def classify_all(incidents: list[Incident]) -> list[FunnelClassification]:
    return [classify(incident, incidents) for incident in incidents]
