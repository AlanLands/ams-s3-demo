"""Who is asking to enrol, and which of them the access preferences anticipated.

Two of these three categories map cleanly onto an access preference, because
the preferences were designed around them. The third does not, and that
mismatch is the reason this app carries an impact-analysis surface at all
(see `impact.py`).

- `MEMBER`   — on the contract's roster and holding at least one active
               benefit. The Member preference was written for this person.
- `GUEST`    — not on the roster at all. Enrolling under a sponsor-agreed
               exception. The Guest preference was written for this person.
- `PROSPECT` — on the contract's roster, holding no active benefit yet.
               Neither preference was written for this person.

A prospect is not a halfway state on the way to becoming a member; it is a
population the sponsor has already accepted onto the roster but who has not
taken up coverage. They are visible to plan administration, which is what
makes treating them as a `GUEST` (a stranger to the contract) uncomfortable,
and treating them as a `MEMBER` (a person with coverage to change) inaccurate.

**No preference is written for them, and this app does not yet pick one.** The
gate resolves a category to a preference; `PROSPECT` resolves to none, so a
prospect is refused at the channel today. That refusal is the current
behaviour, not a decision — see `impact.py`, which sizes both options against
the seeded directory and recommends one. Acting on that recommendation is a
change to the gate that has not been made.
"""

from __future__ import annotations

from dataclasses import dataclass

MEMBER = "MEMBER"
GUEST = "GUEST"
PROSPECT = "PROSPECT"

ALL_CATEGORIES: tuple[str, ...] = (MEMBER, GUEST, PROSPECT)

CATEGORY_DESCRIPTION: dict[str, str] = {
    MEMBER: "On the contract roster, holding at least one active benefit.",
    GUEST: "Not on the contract roster. Enrolling under a sponsor-agreed exception.",
    PROSPECT: "On the contract roster, holding no active benefit yet.",
}

@dataclass(frozen=True)
class Applicant:
    """A person presenting at the online enrolment gate.

    `category` is derived upstream by plan administration, not by this app —
    EnrolDirect is told what someone is, it does not decide. `hasActiveBenefit`
    travels with the record because it is the fact that distinguishes a member
    from a prospect, and the impact analysis reports on it.
    """

    applicantId: str
    fullName: str
    contractNumber: str
    category: str
    hasActiveBenefit: bool

    def __post_init__(self) -> None:
        if self.category not in ALL_CATEGORIES:
            raise ValueError(
                f"unknown applicant category {self.category!r} "
                f"(expected one of {', '.join(ALL_CATEGORIES)})"
            )
        # A member without an active benefit is a prospect that plan
        # administration mislabelled, and a prospect with one is a member it
        # forgot to promote. Both are upstream data faults that would grant or
        # deny the wrong access silently, so they fail loudly at the boundary.
        if self.category == MEMBER and not self.hasActiveBenefit:
            raise ValueError(
                f"applicant {self.applicantId} is categorised MEMBER but holds "
                f"no active benefit — that is a PROSPECT"
            )
        if self.category == PROSPECT and self.hasActiveBenefit:
            raise ValueError(
                f"applicant {self.applicantId} is categorised PROSPECT but "
                f"holds an active benefit — that is a MEMBER"
            )
