"""The access preferences that gate MapleSure's online enrolment channel.

A group contract does not simply "have online enrolment". The plan sponsor
agrees at contract inception *who* may use the self-serve channel, and that
agreement is stored against the contract as one or both of the preferences
below. EnrolDirect enforces them; it does not own them.

That split matters. The preferences are configured in **PolicyCore**, the
plan administration portal, and reach this app as contract data. So a change
to what a preference *means* is a change to a shared contract of two systems,
not a local edit — which is exactly why the population question this app
exists to answer needed an impact analysis before anyone wrote code.

Both preferences are expressed as data rather than branching so that a
sponsor-specific variation is a configuration edit rather than a code change,
matching the convention in `repos/policycore/enrolment/`.
"""

from __future__ import annotations

# The two access preferences as PolicyCore spells them. These strings are the
# integration contract with the plan administration portal, not display labels
# — they arrive verbatim on the contract record. Renaming one here without
# renaming it there silently disables the gate it controls, because an unknown
# preference is absent, and absent means "not granted".
MEMBER_ACCESS = "Online Enrolment - Member"
GUEST_ACCESS = "Online Enrolment - Guest"

ALL_PREFERENCES: tuple[str, ...] = (MEMBER_ACCESS, GUEST_ACCESS)

# What each preference was originally agreed to cover. Held as data because
# the enrolment impact analysis reports it, and a docstring cannot be served
# over HTTP.
PREFERENCE_PURPOSE: dict[str, str] = {
    MEMBER_ACCESS: (
        "Plan members already enrolled in at least one benefit under the "
        "contract, using the self-serve channel to change their own coverage."
    ),
    GUEST_ACCESS: (
        "People with no active benefit under the contract who still have a "
        "reason to enrol — retiree continuations, spousal transfers, and "
        "other sponsor-agreed exceptions."
    ),
}


def is_known_preference(preference: str) -> bool:
    """Whether a preference string is one this app can enforce.

    Called on contract data arriving from PolicyCore. An unrecognised
    preference is a configuration or version mismatch between the two systems,
    and the caller's job is to surface it rather than to treat it as granting
    anything.
    """
    return preference in ALL_PREFERENCES


def unknown_preferences(configured: tuple[str, ...]) -> tuple[str, ...]:
    """The configured preferences this app does not understand.

    Reported on the contract endpoint rather than raising: a contract carrying
    a preference from a newer PolicyCore release should still serve its known
    preferences correctly, and a hard failure here would take the whole
    enrolment channel down for one unrecognised string.
    """
    return tuple(p for p in configured if not is_known_preference(p))
