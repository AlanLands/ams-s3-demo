"""Amendment-request business logic for the MapleSure group benefits app.

Kept separate from db.py so the Streamlit view (app.py) never has to
construct amendment numbers or timestamps itself — it only calls
submit_amendment().
"""

from __future__ import annotations

from datetime import UTC, datetime

from repos.policycore.core.db import insert_amendment, list_amendments
from repos.policycore.core.models import Amendment

_AMENDMENT_PREFIX = "AMD"


def _next_amendment_number(policy_number: str) -> str:
    """Generate a new amendment number, unique across all policies.

    Demo-grade: scans existing amendments for the given policy plus a fixed
    offset so numbers don't collide across policies in this synthetic
    dataset. Good enough for the tabletop demo; not a production ID scheme.
    """
    existing = list_amendments(policy_number)
    seq = len(existing) + 1
    suffix = abs(hash(policy_number)) % 10000
    return f"{_AMENDMENT_PREFIX}-{suffix:04d}{seq:02d}"


def submit_amendment(
    policy_number: str,
    amendment_type: str,
    requested_change: str,
    effective_date: str,
    contact_phone: str,
    contact_email: str,
) -> Amendment:
    """Create and persist a new amendment request, returning the record."""
    amendment = Amendment(
        amendment_number=_next_amendment_number(policy_number),
        policy_number=policy_number,
        amendment_type=amendment_type,
        requested_change=requested_change,
        effective_date=effective_date,
        contact_phone=contact_phone,
        contact_email=contact_email,
        filed_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )
    insert_amendment(amendment)
    return amendment
