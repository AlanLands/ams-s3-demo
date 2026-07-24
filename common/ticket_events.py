"""Append-only ticket timeline events for demo audit trails."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Literal

from common.schema import DATETIME_FMT

Actor = Literal["ai", "human", "system"]
REPO_ROOT = Path(__file__).resolve().parents[1]
EVENTS_PATH = REPO_ROOT / "data" / "ticket_events.jsonl"
# Written by demo/reset_s3.sh only — never touched by normal event recording,
# so (unlike EVENTS_PATH's own mtime, which changes on every single event
# appended) this only ever changes when an actual reset happens. See
# events_log_marker().
RESET_MARKER_PATH = REPO_ROOT / "data" / ".s3_reset_marker"


def _events_path() -> Path:
    return Path(os.environ.get("TICKET_EVENTS_PATH", EVENTS_PATH))


def record_event(ticket_number: str, actor: Actor, action: str, detail: str = "") -> None:
    """Append one timeline event as JSONL.

    Idempotent per (ticket_number, actor, action, detail): a Streamlit
    session reset (e.g. a browser reload) re-runs the whole pipeline script,
    and each pipeline stage is a one-time milestone for a given ticket — this
    must not create duplicate audit entries just because the caller's
    in-memory dedup (st.session_state) doesn't survive a reload. Checking the
    persisted log itself, not just session state, is what makes this safe.
    """
    if actor not in ("ai", "human", "system"):
        raise ValueError(f"Unsupported actor: {actor}")

    for existing in events_for(ticket_number):
        if (
            existing.get("actor") == actor
            and existing.get("action") == action
            and existing.get("detail") == detail
        ):
            return

    path = _events_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "ts": datetime.now().strftime(DATETIME_FMT),
        "ticket_number": ticket_number,
        "actor": actor,
        "action": action,
        "detail": detail,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, sort_keys=True) + "\n")


def events_for(ticket_number: str) -> list[dict]:
    """Return timeline events for one ticket, oldest first."""
    path = _events_path()
    if not path.exists():
        return []

    events: list[dict] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            event = json.loads(line)
            if event.get("ticket_number") == ticket_number:
                events.append(event)
    return events


def distinct_tickets_with_action(action: str) -> set[str]:
    """Ticket numbers with at least one recorded event of `action`, across all
    tickets — used for cross-ticket counts (e.g. a dashboard KPI), unlike
    `events_for` which is scoped to one ticket."""
    path = _events_path()
    if not path.exists():
        return set()

    tickets: set[str] = set()
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            event = json.loads(line)
            if event.get("action") == action:
                tickets.add(event["ticket_number"])
    return tickets


def tickets_with_action_detail(action: str, detail: str) -> set[str]:
    """Like `distinct_tickets_with_action`, but also filtered on `detail` —
    used to look up "which tickets currently carry this exact detail value for
    this action" (e.g. all tickets with an `engineer_assigned` event whose
    detail is a specific engineer's name)."""
    path = _events_path()
    if not path.exists():
        return set()

    tickets: set[str] = set()
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            event = json.loads(line)
            if event.get("action") == action and event.get("detail") == detail:
                tickets.add(event["ticket_number"])
    return tickets


def clear_events() -> None:
    """Remove all recorded ticket timeline events."""
    path = _events_path()
    if path.exists():
        path.unlink()


def events_log_marker() -> str:
    """A value that changes only when `demo/reset_s3.sh` (or equivalent) runs
    — for a caller (the frontend) that caches per-ticket AI results
    client-side and needs to know server state was reset out from under it,
    rather than keep showing results for a ticket the server has no record of
    anymore. Deliberately not derived from EVENTS_PATH's own mtime, which
    changes on every single event appended, not just on a reset."""
    path = Path(os.environ.get("TICKET_RESET_MARKER_PATH", RESET_MARKER_PATH))
    if not path.exists():
        return "0"
    return path.read_text(encoding="utf-8").strip() or "0"
