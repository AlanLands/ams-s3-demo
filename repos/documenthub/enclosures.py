"""What goes in the envelope with each audience's letter.

Separate from `wording.py` for an operational reason rather than a tidiness
one: enclosures are physical. A letter with the wrong paragraph is embarrassing
and can be reissued by email. A pack with the wrong enclosure has asked a real
person to complete and return a real form, and withdrawing that request costs a
phone call each. So the enclosure set attached to an audience is reviewed by
plan administration rather than by Communications, and it moves on its own
schedule.

The two lists below encode the same assumption `wording.audience_for` does, and
it is worth naming here too: the identity confirmation form is attached to the
guest audience because a guest is, by definition, someone MapleSure holds no
member record for. Attach that audience to someone the sponsor lists on its own
roster and the form is not merely redundant — it is a request for proof of
identity from a person already identified, which is the part plan
administration hears about.
"""

from __future__ import annotations

from repos.documenthub.wording import AUDIENCE_GUEST, AUDIENCE_MEMBER

# Enclosure codes as the print vendor knows them. Verbatim strings on the
# vendor's manifest, not display labels.
BENEFIT_SUMMARY = "ENC-BENEFIT-SUMMARY"
CLAIMS_GUIDE = "ENC-CLAIMS-GUIDE"
IDENTITY_FORM = "ENC-IDENTITY-CONFIRMATION"
ROSTER_WELCOME = "ENC-ROSTER-WELCOME"
PRIVACY_NOTICE = "ENC-PRIVACY-NOTICE"

ENCLOSURE_TITLE: dict[str, str] = {
    BENEFIT_SUMMARY: "Summary of your benefit",
    CLAIMS_GUIDE: "How to make a claim",
    IDENTITY_FORM: "Identity confirmation form (return within 30 days)",
    ROSTER_WELCOME: "Welcome to your group plan",
    PRIVACY_NOTICE: "How we handle your personal information",
}

ENCLOSURES: dict[str, tuple[str, ...]] = {
    AUDIENCE_MEMBER: (BENEFIT_SUMMARY, CLAIMS_GUIDE, PRIVACY_NOTICE),
    AUDIENCE_GUEST: (BENEFIT_SUMMARY, CLAIMS_GUIDE, IDENTITY_FORM, PRIVACY_NOTICE),
}


def enclosures_for(audience: str) -> tuple[str, ...]:
    """The enclosure codes for an audience.

    Raises rather than returning an empty tuple for an unknown audience. An
    empty enclosure list is a valid, printable pack — it would go out as a
    letter with nothing in the envelope, and the first anyone would know is a
    call asking where the claim form is.
    """
    if audience not in ENCLOSURES:
        raise KeyError(
            f"no enclosure set is defined for audience {audience!r} "
            f"(known: {', '.join(sorted(ENCLOSURES))})"
        )
    return ENCLOSURES[audience]


def enclosure_title(code: str) -> str:
    """Human title for an enclosure code, falling back to the code itself.

    The fallback is safe here in a way it is not in `enclosures_for`: an
    untitled enclosure prints its code on the manifest, which is ugly but
    correct, and the vendor packs by code regardless.
    """
    return ENCLOSURE_TITLE.get(code, code)
