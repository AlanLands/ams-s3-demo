"""The online enrolment access gate.

One question: may this applicant use the self-serve enrolment channel on this
contract? Three gates decide it, and all three have to be open.

1. **The contract is active.** A lapsed contract keeps whatever preferences it
   was configured with, so this gate runs first — reading preferences off a
   lapsed contract would let stale configuration grant access.
2. **The applicant's category maps to a preference.** Members and guests map
   directly. Prospects map to nothing — no preference was written for them and
   none has been assigned, so they are refused here. That is the open question
   `impact.py` exists to size, not a settled rule.
3. **The contract enables that preference.** The sponsor agreed this at
   inception; see `preferences.py`.

The decision carries its reasons rather than just a boolean. A denial that
cannot say which gate closed produces a support ticket, and an unclassified
prospect being refused is precisely the denial a service desk gets asked to
explain.

Nothing here decides *when* someone may join — waiting periods, life events
and enrolment windows are a different question, owned by
`repos/policycore/enrolment/eligibility.py`. This module answers only whether
the online channel is open to them. The two gates compose; they do not
overlap.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from repos.enroldirect.applicants import GUEST, MEMBER, Applicant
from repos.enroldirect.directory import GroupContract
from repos.enroldirect.preferences import GUEST_ACCESS, MEMBER_ACCESS

ACTIVE = "ACTIVE"


@dataclass(frozen=True)
class EligibilityDecision:
    """The outcome of one access check.

    `authorisingPreference` is the preference that actually opened the gate,
    not the one the applicant's category nominally belongs to. Today those are
    the same for everyone the gate admits, because only members and guests are
    admitted at all. It is recorded separately anyway: it is what DocumentHub
    words the confirmation pack from and what NightlyBatch reconciles on, so it
    has to be the preference that did the work, not one inferred downstream.
    """

    granted: bool
    applicantId: str
    contractNumber: str
    category: str
    # The preference consulted for this applicant, whether or not the contract
    # had it enabled. None when the category resolved to no preference at all.
    requiredPreference: str | None
    # The preference that granted access. None on every denial.
    authorisingPreference: str | None
    reasons: list[str] = field(default_factory=list)


def preference_for_category(category: str) -> str | None:
    """The access preference an applicant category has to be granted under.

    Members and guests each have one. Prospects have none — the two
    preferences were written for the two populations that had been
    anticipated, and returning `None` here is what refuses them at the gate.
    One lookup in one place rather than a branch repeated at each call site,
    so whatever is eventually decided about prospects lands here.
    """
    if category == MEMBER:
        return MEMBER_ACCESS
    if category == GUEST:
        return GUEST_ACCESS
    return None


def check_eligibility(
    applicant: Applicant,
    contract: GroupContract,
) -> EligibilityDecision:
    """Run the three gates for one applicant on one contract."""
    reasons: list[str] = []

    if applicant.contractNumber != contract.contractNumber:
        raise ValueError(
            f"applicant {applicant.applicantId} belongs to contract "
            f"{applicant.contractNumber}, not {contract.contractNumber}"
        )

    # Gate 1 — the contract itself.
    if contract.status != ACTIVE:
        reasons.append(
            f"Contract {contract.contractNumber} is {contract.status}; online "
            f"enrolment is available on active contracts only."
        )
        return EligibilityDecision(
            granted=False,
            applicantId=applicant.applicantId,
            contractNumber=contract.contractNumber,
            category=applicant.category,
            requiredPreference=None,
            authorisingPreference=None,
            reasons=reasons,
        )

    # Gate 2 — does the category resolve to a preference at all?
    required = preference_for_category(applicant.category)
    if required is None:
        reasons.append(
            f"Applicant category {applicant.category} has no online enrolment "
            f"preference and cannot be granted access."
        )
        return EligibilityDecision(
            granted=False,
            applicantId=applicant.applicantId,
            contractNumber=contract.contractNumber,
            category=applicant.category,
            requiredPreference=None,
            authorisingPreference=None,
            reasons=reasons,
        )

    # Gate 3 — has the sponsor enabled that preference?
    if required not in contract.enabledPreferences:
        enabled = ", ".join(contract.enabledPreferences) or "none"
        reasons.append(
            f"Contract {contract.contractNumber} does not enable "
            f"'{required}' (enabled: {enabled})."
        )
        return EligibilityDecision(
            granted=False,
            applicantId=applicant.applicantId,
            contractNumber=contract.contractNumber,
            category=applicant.category,
            requiredPreference=required,
            authorisingPreference=None,
            reasons=reasons,
        )

    reasons.append(f"Granted under '{required}'.")
    return EligibilityDecision(
        granted=True,
        applicantId=applicant.applicantId,
        contractNumber=contract.contractNumber,
        category=applicant.category,
        requiredPreference=required,
        authorisingPreference=required,
        reasons=reasons,
    )
