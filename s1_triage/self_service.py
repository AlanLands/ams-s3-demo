"""Detectors + templated responses for incidents safe to auto-resolve without
engineer review.

Scoped deliberately narrow to a short list of self-service requests — the
textbook "safe to fully automate" ITSM cases: fully reversible, touch only the
requestor's own account, no production or business-system change, and the
response is a fixed template (no AI judgment call), unlike every other
resolution this app drafts. See common/constants.py's AUTO_RESOLVED_LABEL for
the human-in-the-loop exception this implements, and
data/kb_articles/KB0001001_policycore_password_reset.md /
KB0001003_policycore_id_card_resend.md for the underlying procedures these
templates follow.

Adding a third self-service kind: add its keyword tuple, a `_draft_*`
function, and one more entry in `_MATCHERS` below -- `match_self_service()`
and every caller are already generic over the list.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from common.schema import Incident

SelfServiceKind = Literal["password_reset", "id_card_resend"]

_PASSWORD_RESET_KEYWORDS = (
    "forgot my password",
    "forgot password",
    "reset my password",
    "password reset",
    "locked out",
    "account lockout",
    "can't log in",
    "cannot log in",
    "can't sign in",
    "cannot sign in",
)

_ID_CARD_KEYWORDS = (
    "insurance id card",
    "proof of insurance",
    "id card",
    "digital id card",
    "insurance card",
)


@dataclass(frozen=True)
class SelfServiceMatch:
    kind: SelfServiceKind
    confirmation: str


def _draft_password_reset_confirmation(incident: Incident) -> str:
    return (
        f"Hi, this confirms your {incident.application} password reset request has "
        "been processed. A reset link has been sent to the email address already "
        "on file for your account — please sign in again from a fresh browser "
        "session. If you did not request this, contact the Service Desk "
        "immediately."
    )


def _draft_id_card_confirmation(incident: Incident) -> str:
    return (
        f"Hi, this confirms your {incident.application} digital insurance ID card "
        "request has been processed. A copy has been sent to the email address "
        "already on file for your account. If you did not request this, contact "
        "the Service Desk immediately."
    )


# Checked in order -- first match wins. Order only matters if a ticket's text
# could ever match more than one entry, which the keyword lists above are
# written to avoid.
_MATCHERS: tuple[tuple[SelfServiceKind, tuple[str, ...], object], ...] = (
    ("password_reset", _PASSWORD_RESET_KEYWORDS, _draft_password_reset_confirmation),
    ("id_card_resend", _ID_CARD_KEYWORDS, _draft_id_card_confirmation),
)


def match_self_service(incident: Incident) -> SelfServiceMatch | None:
    """Keyword text is not sufficient on its own: "locked out" or "account
    lockout" can just as easily describe a suspected fraud/compromise report as
    a routine reset, and that distinction must never be decided by auto-close.
    Restricting to the seeded self-service shape (category=Access, priority=P4)
    keeps this path scoped to genuinely low-stakes requests; anything else
    with matching text still falls through to full triage and human review.
    """
    if incident.category != "Access" or incident.priority != "P4":
        return None
    text = f"{incident.short_description} {incident.description}".lower()
    for kind, keywords, draft in _MATCHERS:
        if any(keyword in text for keyword in keywords):
            return SelfServiceMatch(kind=kind, confirmation=draft(incident))
    return None
