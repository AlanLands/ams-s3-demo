"""In-memory session store for the API layer.

Server-side identity storage keyed by an httponly cookie — same reliability
posture as Streamlit's own `session_state` (a demo-day process restart is
already a reset event, mirroring `demo/reset_sX.sh`). Single-process only,
matching this project's "one process, one port" deployment story; not meant
to survive a multi-worker/production deployment.
"""

from __future__ import annotations

import secrets
from typing import Any

SESSION_COOKIE_NAME = "ams_session"

_SESSIONS: dict[str, dict[str, Any]] = {}


def create_session() -> str:
    session_id = secrets.token_urlsafe(24)
    _SESSIONS[session_id] = {}
    return session_id


def get_session_data(session_id: str | None) -> dict[str, Any] | None:
    if session_id is None:
        return None
    return _SESSIONS.get(session_id)


def destroy_session(session_id: str | None) -> None:
    if session_id is not None:
        _SESSIONS.pop(session_id, None)
