"""S1 capability 1.0 — data-quality gate.

Scores whether an incoming incident has enough information to investigate. If not,
drafts a mail back to the requestor asking for specifics. Scoped exception to this
app's human-in-the-loop rule: this one mail is auto-sent with no engineer review
(see AUTO_SENT_LABEL in common/constants.py for why) — every other AI output in S1
still waits for a human.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from common.constants import AUTO_SENT_LABEL
from common.llm import LLMError, complete, parse_json_response
from common.schema import Incident, read_csv
from s1_triage.prompts import SYSTEM_PROMPT, build_prompt


@dataclass
class QualityVerdict:
    investigable: bool
    score: float
    missing_info: list[str]
    reasoning: str
    drafted_requestor_mail: str | None


def assess(incident: Incident) -> QualityVerdict:
    response = complete(
        build_prompt(incident),
        system=SYSTEM_PROMPT,
        json_mode=True,
        cache_key=f"s1_quality_gate:{incident.number}",
    )
    data = parse_json_response(response, required_keys={"investigable", "score"})
    try:
        return QualityVerdict(
            investigable=bool(data["investigable"]),
            score=float(data["score"]),
            missing_info=list(data.get("missing_info", [])),
            reasoning=data.get("reasoning", ""),
            drafted_requestor_mail=data.get("drafted_requestor_mail"),
        )
    except (TypeError, ValueError) as exc:
        raise LLMError(f"quality gate response had unexpected field types: {exc}") from exc


def render(incident: Incident, verdict: QualityVerdict) -> str:
    status = "INVESTIGABLE" if verdict.investigable else "REJECTED"
    lines = [
        f"Incident {incident.number}: {status} (score {verdict.score:.2f})",
        f"Reasoning: {verdict.reasoning}",
    ]
    if verdict.missing_info:
        lines.append("Missing info: " + ", ".join(verdict.missing_info))
    if verdict.drafted_requestor_mail:
        lines.append("")
        lines.append(f"--- {AUTO_SENT_LABEL} ---")
        lines.append("Requestor mail (auto-sent, no engineer review):")
        lines.append(verdict.drafted_requestor_mail)
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="S1 data-quality gate")
    parser.add_argument("csv_path")
    parser.add_argument("--row", type=int, required=True, help="0-indexed row number")
    args = parser.parse_args()

    incidents = read_csv(Path(args.csv_path))
    incident = incidents[args.row]
    verdict = assess(incident)
    print(render(incident, verdict))


if __name__ == "__main__":
    main()
