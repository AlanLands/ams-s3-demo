"""Unit tests for EnrolDirect's access-gate building blocks.

A **unit** layer, deliberately distinct from `test_regression_enroldirect.py`.
That suite asserts end-to-end invariants through HTTP; this one calls the
functions directly, so a failure names the function rather than the flow. Both
are checked in, human-authored, and named by no target's `testgen_allowlist`
or `codegen_allowlist` — see `tests/test_s3_testrun.py`, which asserts that
property for the regression suites and is the reason it holds.

The two rules that govern the regression suites govern this file too:

1. **Every assertion holds before and after CR-2026-045.** The CR settles how
   a prospect is classified at the gate, so nothing here asserts a prospect's
   gate outcome or what `preference_for_category` returns for `PROSPECT`.
   What it asserts is the ground the CR must not move: the two classified
   categories, the gate ordering, the data-integrity rules on the applicant
   record, and the preference-vocabulary contract with PolicyCore.
2. **It lives in `tests/`, not under `repos/enroldirect/`.** Anything ending
   `.py` under a target root joins the codegen candidate pool
   (`relevance.py::discover_mockapp_files` rglobs `*.py`/`*.java`), which
   would reshuffle the relevance funnel and desync the committed recordings.
"""

from __future__ import annotations

import pytest

from repos.enroldirect.applicants import GUEST, MEMBER, PROSPECT, Applicant
from repos.enroldirect.directory import GroupContract
from repos.enroldirect.eligibility import (
    ACTIVE,
    check_eligibility,
    preference_for_category,
)
from repos.enroldirect.preferences import (
    GUEST_ACCESS,
    MEMBER_ACCESS,
    is_known_preference,
    unknown_preferences,
)

LAPSED = "LAPSED"


def _contract(
    status: str = ACTIVE,
    preferences: tuple[str, ...] = (MEMBER_ACCESS, GUEST_ACCESS),
) -> GroupContract:
    return GroupContract(
        contractNumber="MS-9001",
        sponsorName="Testbed Manufacturing Inc.",
        status=status,
        enabledPreferences=preferences,
    )


def _applicant(category: str = MEMBER, *, has_benefit: bool | None = None) -> Applicant:
    """An applicant on `_contract()`'s contract.

    `has_benefit` defaults to whatever the category requires, so a caller that
    does not care about the benefit flag cannot accidentally construct the
    combination `Applicant.__post_init__` rejects.
    """
    if has_benefit is None:
        has_benefit = category == MEMBER
    return Applicant(
        applicantId="AP-9001",
        fullName="Jordan Avery",
        contractNumber="MS-9001",
        category=category,
        hasActiveBenefit=has_benefit,
    )


# --- preferences: the integration vocabulary shared with PolicyCore ---------


def test_known_preferences_are_the_two_policycore_spells():
    # These exact strings arrive verbatim on the contract record. An unknown
    # preference is absent, and absent means "not granted" — so a typo here
    # silently disables a gate rather than failing.
    assert is_known_preference(MEMBER_ACCESS)
    assert is_known_preference(GUEST_ACCESS)


def test_unrecognised_preference_is_not_known():
    assert not is_known_preference("Online Enrolment - Prospect")
    assert not is_known_preference("")


def test_unknown_preferences_reports_only_the_unrecognised_ones():
    configured = (MEMBER_ACCESS, "Online Enrolment - Broker", GUEST_ACCESS)
    assert unknown_preferences(configured) == ("Online Enrolment - Broker",)


def test_unknown_preferences_is_empty_when_all_are_understood():
    assert unknown_preferences((MEMBER_ACCESS, GUEST_ACCESS)) == ()


# --- applicant record: upstream data faults fail at the boundary ------------


def test_member_without_active_benefit_is_rejected_as_mislabelled():
    # Categorised MEMBER but holding nothing is a PROSPECT that plan
    # administration mislabelled. Accepting it would grant the wrong access
    # silently, which is why it raises rather than coercing.
    with pytest.raises(ValueError, match="that is a PROSPECT"):
        Applicant(
            applicantId="AP-9002",
            fullName="Sam Beaulieu",
            contractNumber="MS-9001",
            category=MEMBER,
            hasActiveBenefit=False,
        )


def test_prospect_with_active_benefit_is_rejected_as_mislabelled():
    with pytest.raises(ValueError, match="that is a MEMBER"):
        Applicant(
            applicantId="AP-9003",
            fullName="Rowan Whitfield",
            contractNumber="MS-9001",
            category=PROSPECT,
            hasActiveBenefit=True,
        )


def test_unknown_category_is_rejected():
    with pytest.raises(ValueError, match="unknown applicant category"):
        Applicant(
            applicantId="AP-9004",
            fullName="Kit Marchand",
            contractNumber="MS-9001",
            category="RETIREE",
            hasActiveBenefit=False,
        )


# --- category to preference: the two classified populations only ------------


def test_classified_categories_resolve_to_their_own_preference():
    # Asserted as absolute values, not as a comparison. CR-2026-045 changes
    # what PROSPECT resolves to; if it moved either of these, the change would
    # not be contained to the population it was scoped to.
    assert preference_for_category(MEMBER) == MEMBER_ACCESS
    assert preference_for_category(GUEST) == GUEST_ACCESS


# --- the gate ---------------------------------------------------------------


def test_member_on_active_contract_with_preference_enabled_is_granted():
    decision = check_eligibility(_applicant(MEMBER), _contract())
    assert decision.granted is True
    assert decision.authorisingPreference == MEMBER_ACCESS
    assert decision.requiredPreference == MEMBER_ACCESS


def test_guest_is_refused_when_the_sponsor_enabled_member_access_only():
    decision = check_eligibility(_applicant(GUEST), _contract(preferences=(MEMBER_ACCESS,)))
    assert decision.granted is False
    # The preference was consulted, so it is reported; it did not open the
    # gate, so nothing authorised.
    assert decision.requiredPreference == GUEST_ACCESS
    assert decision.authorisingPreference is None


def test_contract_gate_runs_before_the_preference_gate():
    """A lapsed contract is refused even with the preference enabled.

    The ordering is the load-bearing part: a lapsed contract keeps whatever
    preferences it was configured with, so reversing gates 1 and 3 would let
    stale configuration grant access — and every category-level assertion in
    this file would still pass.
    """
    decision = check_eligibility(
        _applicant(MEMBER),
        _contract(status=LAPSED, preferences=(MEMBER_ACCESS, GUEST_ACCESS)),
    )
    assert decision.granted is False
    # Gate 1 returned before any preference was consulted.
    assert decision.requiredPreference is None
    assert decision.authorisingPreference is None


def test_empty_enabled_preferences_is_a_configuration_not_missing_data():
    # A sponsor who administers enrolment themselves enables neither. This
    # must refuse cleanly rather than read as absent data.
    decision = check_eligibility(_applicant(MEMBER), _contract(preferences=()))
    assert decision.granted is False
    assert decision.authorisingPreference is None


def test_applicant_on_a_different_contract_raises():
    other = GroupContract(
        contractNumber="MS-9999",
        sponsorName="Someone Else Ltd.",
        status=ACTIVE,
        enabledPreferences=(MEMBER_ACCESS,),
    )
    with pytest.raises(ValueError, match="belongs to contract"):
        check_eligibility(_applicant(MEMBER), other)


@pytest.mark.parametrize(
    ("category", "contract"),
    [
        (MEMBER, _contract()),
        (MEMBER, _contract(status=LAPSED)),
        (MEMBER, _contract(preferences=())),
        (GUEST, _contract()),
        (GUEST, _contract(preferences=(MEMBER_ACCESS,))),
    ],
)
def test_every_decision_carries_at_least_one_reason(category, contract):
    """Grant or deny, the decision says why.

    A denial that cannot name the gate that closed becomes a support ticket,
    which is the whole reason the decision carries reasons instead of a bool.
    """
    decision = check_eligibility(_applicant(category), contract)
    assert decision.reasons
    assert all(reason.strip() for reason in decision.reasons)


def test_denials_never_carry_an_authorising_preference():
    for contract in (_contract(status=LAPSED), _contract(preferences=())):
        decision = check_eligibility(_applicant(MEMBER), contract)
        assert decision.granted is False
        assert decision.authorisingPreference is None
