"""Endorsement-request business logic for the MapleSure mock app.

Kept separate from db.py so the Streamlit view (app.py) never has to
construct endorsement numbers or timestamps itself — it only calls
submit_endorsement().
"""

from __future__ import annotations

from datetime import UTC, datetime

from mockapp.core.db import insert_endorsement, list_endorsements
from mockapp.core.models import Endorsement

_ENDORSEMENT_PREFIX = "END"

def _next_endorsement_number(policy_number: str) -> str:
    existing = list_endorsements(policy_number)
    seq = len(existing) + 1
    suffix = abs(hash(policy_number)) % 10000
    return f"{_ENDORSEMENT_PREFIX}-{suffix:04d}{seq:02d}"

def submit_endorsement(
    policy_number: str,
    endorsement_type: str,
    requested_change: str,
    effective_date: str,
    contact_phone: str,
    contact_email: str,
    priority: str = "Standard"
) -> Endorsement:
    endorsement = Endorsement(
        endorsement_number=_next_endorsement_number(policy_number),
        policy_number=policy_number,
        endorsement_type=endorsement_type,
        requested_change=requested_change,
        effective_date=effective_date,
        contact_phone=contact_phone,
        contact_email=contact_email,
        filed_at=datetime.now(UTC).isoformat(timespec="seconds"),
        priority=priority
    )
    insert_endorsement(endorsement)
    return endorsement
