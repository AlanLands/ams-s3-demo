"""The enrolment feed DocumentHub receives, and what each field is allowed to mean.

**This module is a contract, not a decision.** Every field below is populated
by EnrolDirect at the moment an enrolment is accepted and arrives here as data.
DocumentHub does not compute any of it, cannot correct any of it, and must not
infer a field it was not sent. That constraint is the whole reason this file is
separate from the ones that produce documents: the moment pack logic starts
deriving `onRoster` for itself, the two systems can disagree about the same
person and the document becomes the lie.

Two fields carry the weight, and they are independent:

- `authorisingPreference` — the access preference that actually opened the
  gate, verbatim as PolicyCore spells it. Not the preference the recipient's
  category nominally belongs to; the one that did the work. This is what the
  pack has always been worded from.
- `onRoster` — whether the plan sponsor lists this person on the contract
  roster. It travels separately because it is *not* derivable from the
  preference. Assuming it is, is the bug this module's docstring exists to
  prevent.

Historically the two moved together, which is why nothing here ever had to
think about them separately: everyone admitted under Guest access was someone
with no place on the roster, and everyone on the roster was admitted under
Member access. That was a property of who EnrolDirect happened to admit, never
a rule, and it was never enforced anywhere. See `DESIGN.md`.

The records below are a seeded day's feed, held in memory. DocumentHub is a
demo target that must run on nothing but the venv (no database, no broker), so
the feed is a literal rather than a subscription — but it is shaped exactly as
the real one is, including the fields this service does not read.
"""

from __future__ import annotations

from dataclasses import dataclass

# The two access preferences as PolicyCore spells them, and as EnrolDirect
# forwards them. These strings are the integration contract — they are compared
# verbatim, never parsed or normalised. Renaming one here without renaming it
# in `repos/enroldirect/preferences.py` silently sends every affected enrolment
# down the unknown-preference path.
MEMBER_ACCESS = "Online Enrolment - Member"
GUEST_ACCESS = "Online Enrolment - Guest"

ALL_PREFERENCES: tuple[str, ...] = (MEMBER_ACCESS, GUEST_ACCESS)


@dataclass(frozen=True)
class EnrolmentRecord:
    """One accepted enrolment, as EnrolDirect hands it over.

    Frozen because a pack is a record of what was true when the enrolment was
    accepted. A document assembler that could edit its own input could produce
    a pack that no enrolment ever justified, and nothing downstream would show
    the difference.
    """

    recordId: str
    applicantId: str
    fullName: str
    contractNumber: str
    sponsorName: str
    planCode: str
    planName: str
    planTier: str
    effectiveDate: str
    authorisingPreference: str
    onRoster: bool

    def __post_init__(self) -> None:
        # An unknown preference fails at the boundary rather than downstream in
        # wording selection. The feed is an integration contract with exactly
        # two known values; a third means EnrolDirect shipped a change this
        # service has not been told about, and generating *some* document
        # anyway is how a member receives a guest's pack.
        if self.authorisingPreference not in ALL_PREFERENCES:
            raise ValueError(
                f"record {self.recordId} carries unknown authorising preference "
                f"{self.authorisingPreference!r} (expected one of "
                f"{', '.join(ALL_PREFERENCES)}) — EnrolDirect and DocumentHub "
                f"are out of step"
            )


# A seeded day's feed.
#
# The first four records are the two combinations this service has always
# received: rostered people admitted under Member access, and non-rostered
# people admitted under Guest access.
#
# `ENR-20260804-005` is the record that does not fit. It is a rostered person
# admitted under Guest access — the combination the confirmation packs were
# never written for. It is seeded here deliberately, and it is not
# hypothetical: it is what EnrolDirect starts sending the day US-2026-045
# ships. Ask this service for its pack today and it will produce one, because
# nothing checks; read the pack and it addresses a person on the sponsor's own
# roster as though we have never heard of them.
RECORDS: tuple[EnrolmentRecord, ...] = (
    EnrolmentRecord(
        recordId="ENR-20260804-001",
        applicantId="APP-1001",
        fullName="Marguerite Boulanger",
        contractNumber="GC-40017",
        sponsorName="Boreal Freight Cooperative",
        planCode="DEN-CORE",
        planName="Dental Core",
        planTier="Standard",
        effectiveDate="2026-09-01",
        authorisingPreference=MEMBER_ACCESS,
        onRoster=True,
    ),
    EnrolmentRecord(
        recordId="ENR-20260804-002",
        applicantId="APP-1002",
        fullName="Desmond Achebe",
        contractNumber="GC-40017",
        sponsorName="Boreal Freight Cooperative",
        planCode="VIS-PLUS",
        planName="Vision Plus",
        planTier="Premium",
        effectiveDate="2026-09-01",
        authorisingPreference=MEMBER_ACCESS,
        onRoster=True,
    ),
    EnrolmentRecord(
        recordId="ENR-20260804-003",
        applicantId="APP-1003",
        fullName="Priya Raghunathan",
        contractNumber="GC-40022",
        sponsorName="Lakehead Municipal Services",
        planCode="DEN-CORE",
        planName="Dental Core",
        planTier="Standard",
        effectiveDate="2026-09-15",
        authorisingPreference=GUEST_ACCESS,
        onRoster=False,
    ),
    EnrolmentRecord(
        recordId="ENR-20260804-004",
        applicantId="APP-1004",
        fullName="Tomas Lindqvist",
        contractNumber="GC-40022",
        sponsorName="Lakehead Municipal Services",
        planCode="EHC-BASE",
        planName="Extended Health Base",
        planTier="Standard",
        effectiveDate="2026-09-15",
        authorisingPreference=GUEST_ACCESS,
        onRoster=False,
    ),
    EnrolmentRecord(
        recordId="ENR-20260804-005",
        applicantId="APP-1005",
        fullName="Aditi Varma",
        contractNumber="GC-40017",
        sponsorName="Boreal Freight Cooperative",
        planCode="EHC-BASE",
        planName="Extended Health Base",
        planTier="Standard",
        effectiveDate="2026-10-01",
        authorisingPreference=GUEST_ACCESS,
        onRoster=True,
    ),
)


def all_records() -> tuple[EnrolmentRecord, ...]:
    return RECORDS


def get_record(record_id: str) -> EnrolmentRecord | None:
    """One record by id, or None. None means "not in today's feed" — callers
    turn that into a 404 rather than into an empty pack."""
    for record in RECORDS:
        if record.recordId == record_id:
            return record
    return None
