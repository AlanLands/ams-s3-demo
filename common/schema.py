"""Canonical incident record contract shared by S1, S2, and S6.

`data/incidents.csv` is generated to this schema by `datagen/generate_incidents.py`
and consumed as-is by every scenario module. Never hand-edit the CSV.
"""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from pathlib import Path

from common.constants import ASSIGNMENT_GROUPS, PRIORITIES

DATETIME_FMT = "%Y-%m-%d %H:%M:%S"


@dataclass
class Incident:
    # identity
    number: str
    opened_at: str
    application: str
    business_service: str
    ci: str

    # classification
    category: str
    subcategory: str
    priority: str
    contact_type: str
    caller_role: str
    location: str

    # routing
    assignment_group: str
    reassignment_count: int

    # narrative
    short_description: str
    description: str

    # resolution
    resolution_notes: str
    resolution_category: str
    resolved_at: str

    # SLA
    sla_due: str
    sla_breached: bool

    # problem linkage
    problem_id: str
    known_error_id: str

    # seed lineage (verification only — not shown in any UI)
    source_seed: str
    tags: str


FIELDS = [f.name for f in fields(Incident)]


def _parse_dt(value: str) -> datetime:
    return datetime.strptime(value, DATETIME_FMT)


def validate(incident: Incident) -> list[str]:
    """Return a list of validation error strings; empty list means valid."""
    errors: list[str] = []

    if incident.priority not in PRIORITIES:
        errors.append(f"{incident.number}: priority {incident.priority!r} not in {PRIORITIES}")

    if incident.assignment_group not in ASSIGNMENT_GROUPS:
        errors.append(
            f"{incident.number}: assignment_group {incident.assignment_group!r} not recognized"
        )

    try:
        opened = _parse_dt(incident.opened_at)
    except ValueError:
        errors.append(f"{incident.number}: opened_at {incident.opened_at!r} not parseable")
        opened = None

    if incident.resolved_at:
        try:
            resolved = _parse_dt(incident.resolved_at)
            if opened is not None and resolved < opened:
                errors.append(f"{incident.number}: resolved_at is before opened_at")
        except ValueError:
            errors.append(f"{incident.number}: resolved_at {incident.resolved_at!r} not parseable")

    if incident.sla_due:
        try:
            sla_due = _parse_dt(incident.sla_due)
            if incident.resolved_at:
                resolved = _parse_dt(incident.resolved_at)
                breached = resolved > sla_due
                if breached != incident.sla_breached:
                    errors.append(
                        f"{incident.number}: sla_breached={incident.sla_breached} "
                        f"inconsistent with resolved_at vs sla_due"
                    )
        except ValueError:
            errors.append(f"{incident.number}: sla_due {incident.sla_due!r} not parseable")

    return errors


def write_csv(incidents: list[Incident], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for incident in incidents:
            writer.writerow(asdict(incident))


def read_csv(path: Path) -> list[Incident]:
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        incidents = []
        for row in reader:
            row["reassignment_count"] = int(row["reassignment_count"])
            row["sla_breached"] = row["sla_breached"] in ("True", "true", "1")
            incidents.append(Incident(**row))
        return incidents
