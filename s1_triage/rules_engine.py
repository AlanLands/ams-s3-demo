"""Editable per-application rule engine for S1 triage."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from common.constants import APPLICATIONS, PRIORITIES
from common.schema import Incident

RULES_DIR = Path(__file__).resolve().parent / "rules"


@dataclass(frozen=True)
class Rule:
    name: str
    keywords: tuple[str, ...]
    suggested_category: str
    suggested_priority: str
    why: str


@dataclass(frozen=True)
class RuleMatch:
    rule_name: str
    suggested_category: str
    suggested_priority: str
    why: str


def _rule_filename(application: str) -> str:
    normalized = "".join(ch for ch in application.lower() if ch.isalnum())
    return f"{normalized}.yaml"


def _parse_rule_file(path: Path) -> Rule:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition(":")
        if not sep:
            raise ValueError(f"{path}: rule line must use 'key: value' format")
        values[key.strip().lower()] = value.strip()

    missing = {"name", "keywords", "category", "priority", "why"} - values.keys()
    if missing:
        raise ValueError(f"{path}: missing required rule fields: {sorted(missing)}")

    keywords = tuple(
        keyword.strip().lower()
        for keyword in values["keywords"].split(",")
        if keyword.strip()
    )
    priority = values["priority"].upper()
    if priority not in PRIORITIES:
        raise ValueError(f"{path}: priority {priority!r} is not recognized")
    if not keywords:
        raise ValueError(f"{path}: at least one keyword is required")

    return Rule(
        name=values["name"],
        keywords=keywords,
        suggested_category=values["category"],
        suggested_priority=priority,
        why=values["why"],
    )


def load_rules(application: str) -> list[Rule]:
    if application not in APPLICATIONS:
        return []
    path = RULES_DIR / _rule_filename(application)
    if not path.exists():
        return []
    return [_parse_rule_file(path)]


def _incident_text(incident: Incident) -> str:
    return " ".join(
        [
            incident.application,
            incident.category,
            incident.subcategory,
            incident.short_description,
            incident.description,
            incident.known_error_id,
            incident.problem_id,
            incident.tags,
        ]
    ).lower()


def apply_rules(incident: Incident) -> RuleMatch | None:
    text = _incident_text(incident)
    for rule in load_rules(incident.application):
        matched_keywords = [keyword for keyword in rule.keywords if keyword in text]
        if matched_keywords:
            why = f"{rule.why} Matched keywords: {', '.join(matched_keywords)}."
            return RuleMatch(
                rule_name=rule.name,
                suggested_category=rule.suggested_category,
                suggested_priority=rule.suggested_priority,
                why=why,
            )
    return None
