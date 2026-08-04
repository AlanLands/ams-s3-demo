"""Which pack a recipient gets, and what that pack says.

DocumentHub does not write one confirmation letter with variable substitutions.
It holds a small number of *audiences* — whole worded packs, each addressed to
someone in a particular relationship with the plan sponsor — and picks one. The
difference matters because the variable parts are not the words that go wrong.
A pack sent to the wrong audience is grammatical, correctly spelled, carries
the right name and the right plan, and is still the wrong document: it tells
the recipient something untrue about how MapleSure knows them.

**Selection is the load-bearing part of this module, not the prose.** The
prose is reviewed by Communications and changes on their schedule.
`audience_for` decides who receives which, and it is the only place in the
service that makes that decision — deliberately, so that adding an audience is
one edit rather than a hunt for every branch that happened to test a
preference.

Today it resolves purely on the authorising preference. That is a narrower
input than the decision needs, and `DESIGN.md` records why it was ever
sufficient and why it is about to stop being.
"""

from __future__ import annotations

from dataclasses import dataclass

from repos.documenthub.feed import GUEST_ACCESS, MEMBER_ACCESS, EnrolmentRecord

# Audience identifiers. Internal to this service — they name a worded pack, and
# they are deliberately not the preference strings: the preference is an access
# decision made by another system, the audience is an editorial decision made
# here, and the two have been one-to-one only by accident.
AUDIENCE_MEMBER = "MEMBER_PACK"
AUDIENCE_GUEST = "GUEST_PACK"

ALL_AUDIENCES: tuple[str, ...] = (AUDIENCE_MEMBER, AUDIENCE_GUEST)


@dataclass(frozen=True)
class Wording:
    """One audience's worded pack.

    `relationship` is the paragraph that states how MapleSure knows the
    recipient. It is the sentence that is wrong when the audience is wrong, and
    it is held as its own field rather than folded into `opening` so that a
    reviewer comparing two audiences can see the claim each one makes.

    `assumesNoMemberRecord` states, as data, whether this pack's prose and
    enclosures are written on the premise that MapleSure holds no member record
    for the recipient. It exists so that the claim can be checked against the
    feed by something other than the rule that chose the pack — see
    `main.audit_selection_inputs`. A rule cannot audit itself, and a flag that
    only the rule sets would be exactly that. Any audience added later must set
    it honestly; a pack that asks for proof of identity is making this claim
    whether or not it declares it.
    """

    audience: str
    description: str
    salutation: str
    opening: str
    relationship: str
    nextSteps: str
    closing: str
    assumesNoMemberRecord: bool


WORDING: dict[str, Wording] = {
    AUDIENCE_MEMBER: Wording(
        audience=AUDIENCE_MEMBER,
        description=(
            "For a plan member already holding coverage under the contract, "
            "who has changed or added to it."
        ),
        salutation="Dear {fullName},",
        opening=(
            "Your enrolment in {planName} ({planTier}) under your group "
            "benefits plan with {sponsorName} is confirmed, effective "
            "{effectiveDate}."
        ),
        relationship=(
            "This plan has been added alongside the benefits you already hold "
            "under group contract {contractNumber}. Your existing coverage is "
            "unaffected and continues without interruption."
        ),
        nextSteps=(
            "Your updated benefits card will arrive within ten business days. "
            "You can review your full coverage at any time through the member "
            "portal using your existing sign-in."
        ),
        closing=(
            "If anything above does not match what you selected, contact your "
            "plan administrator at {sponsorName} before the effective date."
        ),
        assumesNoMemberRecord=False,
    ),
    AUDIENCE_GUEST: Wording(
        audience=AUDIENCE_GUEST,
        description=(
            "For someone with no place on the sponsor's roster, enrolling "
            "under a sponsor-agreed exception — a retiree continuation, a "
            "spousal transfer, or similar."
        ),
        salutation="Dear {fullName},",
        opening=(
            "Your enrolment in {planName} ({planTier}) is confirmed, effective "
            "{effectiveDate}."
        ),
        # The claim this audience makes: we do not have you on file, so tell us
        # who you are. Correct for a stranger to the contract. Read by someone
        # the sponsor has listed on its own roster, it says MapleSure has lost
        # them.
        relationship=(
            "You are enrolling under an arrangement agreed by {sponsorName} "
            "rather than as a listed member of group contract "
            "{contractNumber}. Because we hold no member record for you, we "
            "need you to confirm your identity and contact details before "
            "coverage can be used."
        ),
        nextSteps=(
            "Complete and return the enclosed identity confirmation form "
            "within thirty days. Your benefits card will be issued once it has "
            "been received and checked."
        ),
        closing=(
            "If you believe you should already be listed on this contract, "
            "contact your plan administrator at {sponsorName} — do not return "
            "the enclosed form."
        ),
        # The premise behind the paragraph above and behind the identity form
        # in this audience's enclosure set.
        assumesNoMemberRecord=True,
    ),
}


def audience_for(record: EnrolmentRecord) -> str:
    """The audience whose pack this record should receive.

    The service's single selection point. It reads one fact — the preference
    that authorised the enrolment — and that is the whole of the decision
    today.

    The `else` is a fall-through rather than an explicit `GUEST_ACCESS` test,
    and that is not laziness: `feed.EnrolmentRecord` rejects any preference
    outside the two known ones at construction, so by the time a record reaches
    here "not Member" means Guest and a third branch would be unreachable. The
    consequence is worth stating plainly, because it is the behaviour that
    matters when the set of recipients changes: **anyone this function is not
    sure about receives the guest pack.** Nothing here reports being unsure.
    """
    if record.authorisingPreference == MEMBER_ACCESS:
        return AUDIENCE_MEMBER
    return AUDIENCE_GUEST


def wording_for(audience: str) -> Wording:
    """The worded pack for an audience.

    Raises on an unknown audience rather than substituting a default. A
    document service that silently falls back produces a plausible pack for a
    recipient nobody chose wording for, which is indistinguishable from
    correct until someone reads it.
    """
    if audience not in WORDING:
        raise KeyError(
            f"no wording is defined for audience {audience!r} "
            f"(known: {', '.join(sorted(WORDING))})"
        )
    return WORDING[audience]


def audience_catalogue() -> list[dict[str, str]]:
    """Every audience this service can produce, for the operator console."""
    return [
        {"audience": w.audience, "description": w.description}
        for w in (WORDING[name] for name in ALL_AUDIENCES)
    ]


__all__ = [
    "AUDIENCE_GUEST",
    "AUDIENCE_MEMBER",
    "ALL_AUDIENCES",
    "GUEST_ACCESS",
    "MEMBER_ACCESS",
    "WORDING",
    "Wording",
    "audience_catalogue",
    "audience_for",
    "wording_for",
]
