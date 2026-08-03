"""Seeded group contracts and applicants.

All synthetic. The plan sponsors are fictional employers and every applicant
name is invented; nothing here derives from a real roster.

In production this data arrives from PolicyCore over the plan-administration
feed. It is seeded in-process here for the same reason ClaimsPortal seeds its
contracts in `policy_service/main.py` — the app has to run in a locked-down
sandbox with nothing but the venv, so an external datastore is a dependency it
cannot take.

The seed is shaped deliberately. Every combination of enabled preferences
appears at least once, and prospects sit on contracts whose preferences point
in opposite directions, so the prospect impact comparison in `impact.py` has
genuine disagreement to report. A seed where both policies produced the same
answer everywhere would make the analysis look decisive and prove nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from repos.enroldirect.applicants import GUEST, MEMBER, PROSPECT, Applicant
from repos.enroldirect.preferences import GUEST_ACCESS, MEMBER_ACCESS


@dataclass(frozen=True)
class GroupContract:
    """A group benefit contract, as EnrolDirect receives it.

    `enabledPreferences` is the sponsor's agreement about who may use the
    self-serve channel. An empty tuple is a real and common configuration —
    the sponsor administers enrolment themselves — and must not be read as
    missing data.
    """

    contractNumber: str
    sponsorName: str
    status: str  # "ACTIVE" | "LAPSED"
    enabledPreferences: tuple[str, ...] = field(default_factory=tuple)


CONTRACTS: list[GroupContract] = [
    GroupContract(
        contractNumber="MS-2001",
        sponsorName="Northwind Logistics Ltd.",
        status="ACTIVE",
        enabledPreferences=(MEMBER_ACCESS, GUEST_ACCESS),
    ),
    GroupContract(
        contractNumber="MS-2002",
        sponsorName="Cedarline Manufacturing Inc.",
        status="ACTIVE",
        enabledPreferences=(MEMBER_ACCESS,),
    ),
    GroupContract(
        contractNumber="MS-2003",
        sponsorName="Quill & Fenwick LLP",
        status="ACTIVE",
        enabledPreferences=(GUEST_ACCESS,),
    ),
    GroupContract(
        contractNumber="MS-2004",
        sponsorName="Talus Software Co.",
        status="ACTIVE",
        enabledPreferences=(),
    ),
    GroupContract(
        contractNumber="MS-2005",
        sponsorName="Harbourline Freight Co-operative",
        status="LAPSED",
        enabledPreferences=(MEMBER_ACCESS, GUEST_ACCESS),
    ),
]

APPLICANTS: list[Applicant] = [
    # MS-2001 — both preferences on. The prospect here is granted either way,
    # which is what makes the two policies look equivalent until you look at
    # the contracts that only enabled one of them.
    Applicant("AP-4001", "Rowan Iqbal", "MS-2001", MEMBER, True),
    Applicant("AP-4002", "Priya Chandrasekar", "MS-2001", GUEST, False),
    Applicant("AP-4003", "Devon Achebe", "MS-2001", PROSPECT, False),
    # MS-2002 — Member only. This prospect is granted under TREAT_AS_MEMBER
    # and denied under TREAT_AS_GUEST.
    Applicant("AP-4004", "Sena Okonkwo", "MS-2002", MEMBER, True),
    Applicant("AP-4005", "Marguerite Vasseur", "MS-2002", PROSPECT, False),
    Applicant("AP-4006", "Tobias Lindqvist", "MS-2002", PROSPECT, False),
    # MS-2003 — Guest only. The disagreement runs the other way here.
    Applicant("AP-4007", "Hana Yamashita", "MS-2003", GUEST, False),
    Applicant("AP-4008", "Emeka Balogun", "MS-2003", PROSPECT, False),
    # MS-2004 — no online enrolment at all. Nobody is granted regardless of
    # category or policy, which is the case that proves the analysis is
    # reading contract configuration rather than category alone.
    Applicant("AP-4009", "Camille Fortier", "MS-2004", MEMBER, True),
    Applicant("AP-4010", "Ingrid Solberg", "MS-2004", PROSPECT, False),
    # MS-2005 — lapsed contract with both preferences still configured. The
    # contract gate has to run before the preference gate, or a lapsed
    # contract's stale configuration grants access.
    Applicant("AP-4011", "Bashir Haddad", "MS-2005", MEMBER, True),
    Applicant("AP-4012", "Lucia Moreau", "MS-2005", PROSPECT, False),
]

CONTRACTS_BY_NUMBER: dict[str, GroupContract] = {c.contractNumber: c for c in CONTRACTS}
APPLICANTS_BY_ID: dict[str, Applicant] = {a.applicantId: a for a in APPLICANTS}


def get_contract(contract_number: str) -> GroupContract | None:
    return CONTRACTS_BY_NUMBER.get(contract_number)


def get_applicant(applicant_id: str) -> Applicant | None:
    return APPLICANTS_BY_ID.get(applicant_id)


def prospects() -> list[Applicant]:
    """Every seeded applicant in the unclassified population.

    The impact analysis runs on exactly this set, so it lives here next to the
    seed rather than being re-derived by a comprehension at each call site.
    """
    return [a for a in APPLICANTS if a.category == PROSPECT]
