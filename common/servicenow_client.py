"""ServiceNow-shaped record store behind one adapter surface.

Mirrors the `common/llm.py` discipline: callers only ever see the dataclasses
below — no backend detail (JSON store today, Table API later) leaks past this
module. `SN_MODE` selects the backend:

- `mock` (default, the demo path): records live in `data/servicenow_mock.json`.
  This is what the "ServiceNow — simulated" viewer page renders, and it is the
  path that survives a locked-down sandbox with no outbound network.
- `live`: intentionally an interface-only stub. The client's ServiceNow API
  access was never available to test against, so per the never-claim-unbuilt
  rule no untested Table API code ships — the presenter frames live mode as a
  config flip on the roadmap, and this is where that flip would land.

Every successful write also records a `common.ticket_events` entry, keeping the
JSONL audit trail the single source of truth for ticket history.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from common.schema import DATETIME_FMT
from common.ticket_events import Actor, record_event

REPO_ROOT = Path(__file__).resolve().parents[1]
MOCK_STORE_PATH = REPO_ROOT / "data" / "servicenow_mock.json"


class SnError(Exception):
    """Raised for any ServiceNow backend failure or misconfiguration."""


@dataclass(frozen=True)
class SnWorkNote:
    ts: str
    actor: Actor
    text: str


@dataclass(frozen=True)
class SnRecord:
    number: str
    table: str  # "problem" | "incident"
    short_description: str
    state: str
    opened_at: str
    linked_records: list[str] = field(default_factory=list)
    work_notes: list[SnWorkNote] = field(default_factory=list)


def _mode() -> str:
    mode = os.environ.get("SN_MODE", "mock").lower()
    if mode not in {"mock", "live"}:
        raise SnError(f"Unknown SN_MODE {mode!r}; expected 'mock' or 'live'")
    return mode


def _require_mock() -> None:
    if _mode() == "live":
        raise SnError(
            "SN_MODE=live is not configured — live Table API support is the "
            "roadmap drop-in point; mock is the demo path"
        )


def _store_path() -> Path:
    return Path(os.environ.get("SN_MOCK_STORE_PATH", MOCK_STORE_PATH))


def _now() -> str:
    return datetime.now().strftime(DATETIME_FMT)


def _load_store() -> dict[str, dict]:
    path = _store_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SnError(f"Mock store {path} is not valid JSON") from exc
    return data.get("records", {})


def _save_store(records: dict[str, dict]) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"records": records}, indent=2, sort_keys=False), encoding="utf-8"
    )


def _to_record(raw: dict) -> SnRecord:
    return SnRecord(
        number=raw["number"],
        table=raw["table"],
        short_description=raw["short_description"],
        state=raw["state"],
        opened_at=raw["opened_at"],
        linked_records=list(raw.get("linked_records", [])),
        work_notes=[SnWorkNote(**note) for note in raw.get("work_notes", [])],
    )


def create_problem(
    number: str, short_description: str, affected_incidents: list[str]
) -> SnRecord:
    """Create (or return the already-created) problem record.

    Idempotent by record number: a Streamlit reload re-runs the approve
    handler, and that must not raise or duplicate — same rationale as
    `ticket_events.record_event`.
    """
    _require_mock()
    records = _load_store()
    if number in records:
        return _to_record(records[number])

    record = SnRecord(
        number=number,
        table="problem",
        short_description=short_description,
        state="New",
        opened_at=_now(),
        linked_records=list(affected_incidents),
        work_notes=[
            SnWorkNote(
                ts=_now(),
                actor="system",
                text=f"Problem record created; {len(affected_incidents)} incidents linked.",
            )
        ],
    )
    records[number] = asdict(record)
    _save_store(records)
    record_event(
        number,
        "system",
        "posted_to_servicenow",
        f"Problem record created in simulated ServiceNow "
        f"({len(affected_incidents)} incidents linked)",
    )
    return record


def ensure_incident(number: str, short_description: str = "") -> SnRecord:
    """Return the incident record, creating a thin one if it doesn't exist yet.

    S1 write-back targets incidents that originate in incidents.csv, not in
    this store — the store only needs a record shell to hang work notes on.
    """
    _require_mock()
    records = _load_store()
    if number in records:
        return _to_record(records[number])

    record = SnRecord(
        number=number,
        table="incident",
        short_description=short_description,
        state="In Progress",
        opened_at=_now(),
    )
    records[number] = asdict(record)
    _save_store(records)
    return record


def add_work_note(number: str, text: str, actor: Actor) -> SnRecord:
    """Append a work note to an existing record and return the updated record."""
    _require_mock()
    if not text.strip():
        raise SnError("Work note text is empty")
    records = _load_store()
    if number not in records:
        raise SnError(f"No record {number!r} in the simulated ServiceNow store")

    records[number].setdefault("work_notes", []).append(
        asdict(SnWorkNote(ts=_now(), actor=actor, text=text))
    )
    _save_store(records)
    record_event(number, actor, "work_note_added", text[:200])
    return _to_record(records[number])


def get_record(number: str) -> SnRecord | None:
    _require_mock()
    raw = _load_store().get(number)
    return _to_record(raw) if raw else None


def list_records() -> list[SnRecord]:
    """All records, most recently created first (insertion order reversed)."""
    _require_mock()
    return [_to_record(raw) for raw in reversed(list(_load_store().values()))]


def clear_records() -> None:
    """Remove the mock store — used by demo reset scripts."""
    path = _store_path()
    if path.exists():
        path.unlink()
