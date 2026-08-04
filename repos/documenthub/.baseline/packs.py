"""Assembling one confirmation pack from one enrolment record.

The assembly step is deliberately dull. It resolves an audience, fetches that
audience's wording and enclosures, and fills the placeholders from the record.
It makes no decisions of its own — every judgement lives in
`wording.audience_for`, and the reason is that a decision made in two places
is a decision that can disagree with itself. If assembly could also inspect the
record, a pack's letter and its enclosures could be chosen on different
grounds, and the envelope would contradict the page inside it.

The rendered pack reports the audience it used. That field is not decoration:
it is what makes a wrong pack findable in bulk after the fact, without
re-deriving the decision from the record and getting the same wrong answer
twice.
"""

from __future__ import annotations

from dataclasses import dataclass

from repos.documenthub import enclosures, wording
from repos.documenthub.feed import EnrolmentRecord


@dataclass(frozen=True)
class Pack:
    """A rendered confirmation pack, ready to hand to the print vendor."""

    recordId: str
    applicantId: str
    fullName: str
    audience: str
    salutation: str
    opening: str
    relationship: str
    nextSteps: str
    closing: str
    enclosures: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "recordId": self.recordId,
            "applicantId": self.applicantId,
            "fullName": self.fullName,
            "audience": self.audience,
            "salutation": self.salutation,
            "opening": self.opening,
            "relationship": self.relationship,
            "nextSteps": self.nextSteps,
            "closing": self.closing,
            "enclosures": [
                {"code": code, "title": enclosures.enclosure_title(code)}
                for code in self.enclosures
            ],
        }

    def body_text(self) -> str:
        """The letter as one block, in reading order.

        Used by the operator console and by anyone eyeballing a pack. The
        enclosures are not part of it — they are a separate physical artifact,
        and running them into the letter text would let a reviewer skim past
        the one that should not be there.
        """
        return "\n\n".join(
            (self.salutation, self.opening, self.relationship, self.nextSteps, self.closing)
        )


def _fill(template: str, record: EnrolmentRecord) -> str:
    """Substitute record fields into a wording template.

    `KeyError` propagates rather than being swallowed: a template naming a
    field the record does not carry is an authoring mistake, and the failure
    mode of catching it is a pack that goes out with a literal `{planName}` in
    the body.
    """
    return template.format(
        fullName=record.fullName,
        sponsorName=record.sponsorName,
        contractNumber=record.contractNumber,
        planCode=record.planCode,
        planName=record.planName,
        planTier=record.planTier,
        effectiveDate=record.effectiveDate,
    )


def build_pack(record: EnrolmentRecord) -> Pack:
    """Render the confirmation pack for one enrolment record."""
    audience = wording.audience_for(record)
    words = wording.wording_for(audience)
    return Pack(
        recordId=record.recordId,
        applicantId=record.applicantId,
        fullName=record.fullName,
        audience=audience,
        salutation=_fill(words.salutation, record),
        opening=_fill(words.opening, record),
        relationship=_fill(words.relationship, record),
        nextSteps=_fill(words.nextSteps, record),
        closing=_fill(words.closing, record),
        enclosures=enclosures.enclosures_for(audience),
    )


def audience_breakdown(records: tuple[EnrolmentRecord, ...]) -> dict[str, int]:
    """How many packs of each audience a batch would produce.

    Every known audience appears, including the ones with a count of zero. An
    audience that exists but is never selected is the interesting case — it
    means wording was written for a recipient the selection rule cannot
    actually reach — and omitting empty keys would hide exactly that.
    """
    counts = {audience: 0 for audience in wording.ALL_AUDIENCES}
    for record in records:
        counts[wording.audience_for(record)] += 1
    return counts
