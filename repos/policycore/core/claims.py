"""Benefit-claim submission business logic for the MapleSure mock app.

Kept separate from db.py so the Streamlit view (app.py) never has to
construct claim numbers, timestamps, or default status itself — it only
calls submit_claim().
"""

from __future__ import annotations

from datetime import UTC, datetime

from repos.policycore.core.db import insert_claim, list_claims
from repos.policycore.core.models import Claim

_CLAIM_PREFIX = "CLM"


def _next_claim_number(policy_number: str) -> str:
    """Generate a new claim number, unique across all policies.

    Demo-grade: scans existing claims for the given policy plus a fixed
    offset so numbers don't collide across policies in this synthetic
    dataset. Good enough for the tabletop demo; not a production ID scheme.
    """
    existing = list_claims(policy_number)
    seq = len(existing) + 1
    suffix = abs(hash(policy_number)) % 10000
    return f"{_CLAIM_PREFIX}-{suffix:04d}{seq:02d}"


def submit_claim(
    policy_number: str,
    claim_type: str,
    amount: float,
    notes: str = "",
    member_id: str = "",
) -> Claim:
    """Create and persist a new benefit claim, returning the record.

    member_id is optional and last: it identifies the plan member who incurred
    the expense, but pre-existing call sites predate the plan-member layer and
    submit against the group contract alone.
    """
    claim = Claim(
        claim_number=_next_claim_number(policy_number),
        policy_number=policy_number,
        claim_type=claim_type,
        amount=amount,
        status="Submitted",
        filed_at=datetime.now(UTC).isoformat(timespec="seconds"),
        notes=notes,
        member_id=member_id,
    )
    insert_claim(claim)
    return claim
