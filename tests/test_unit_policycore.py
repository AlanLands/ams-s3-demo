"""Unit tests for PolicyCore's record contracts.

The dataclasses in `repos/policycore/core/models.py` carry a **field-order
contract** that `repos/policycore/AGENTS.md` pins explicitly and that
`core/seed.py` depends on: seed data is constructed with positional arguments,
so a field inserted anywhere but the end — or added without a default —
breaks seeding rather than the model. That failure surfaces at reseed time,
well away from the edit that caused it, which is what makes it worth a test.

Every assertion here holds before and after every CR. Nothing asserts the
*presence* of a field a CR introduces (`plan_tier` for CR-2026-041, amendment
`priority` for CR-2026-042) — those are the changes under test and belong in
the generated suites. What is asserted instead is the property those CRs must
preserve: **the positional call sites that predate them keep working.**

Lives in `tests/` rather than under `repos/policycore/`, for the reason
documented at the top of `test_regression_policycore.py`: a `.py` file under a
target root joins the codegen candidate pool and desyncs the recordings.
"""

from __future__ import annotations

import dataclasses

import pytest

from repos.policycore.core.models import Amendment, Claim, PlanMember, Policy

# --- Policy: seed.py's six positional arguments -----------------------------


def test_policy_accepts_the_six_positional_arguments_seed_uses():
    """`core/seed.py` constructs every Policy positionally, in this order.

    Asserted as a construction rather than as a field list so it keeps holding
    when a CR appends a new trailing field with a default — which is exactly
    what CR-2026-041 does — and starts failing the moment one is inserted
    earlier or made required.
    """
    policy = Policy(
        "MS-1001",
        "Northwind Logistics Ltd.",
        "Health",
        1450.00,
        "2024-03-01",
        "Active",
    )

    assert policy.policy_number == "MS-1001"
    assert policy.sponsor_name == "Northwind Logistics Ltd."
    assert policy.product_type == "Health"
    assert policy.contribution == 1450.00
    assert policy.start_date == "2024-03-01"
    assert policy.status == "Active"


def test_every_policy_field_after_the_sixth_has_a_default():
    """Anything a CR appends must be optional, or seeding breaks.

    The six above are required by design. Field seven onward is territory a
    CR may extend, and the contract is that it extends it with defaults.
    """
    fields = dataclasses.fields(Policy)
    for extra in fields[6:]:
        has_default = (
            extra.default is not dataclasses.MISSING
            or extra.default_factory is not dataclasses.MISSING  # type: ignore[misc]
        )
        assert has_default, f"Policy.{extra.name} was added without a default"


def test_the_first_six_policy_fields_keep_their_order():
    names = [f.name for f in dataclasses.fields(Policy)[:6]]
    assert names == [
        "policy_number",
        "sponsor_name",
        "product_type",
        "contribution",
        "start_date",
        "status",
    ]


# --- Claim: the pre-plan-member positional call sites -----------------------


def test_claim_accepts_the_positional_call_that_predates_the_member_layer():
    # member_id and notes are last with defaults precisely so these call sites
    # keep working; a claim filed against the group contract alone is valid.
    claim = Claim(
        "CLM-100101",
        "MS-1001",
        "Paramedical",
        240.00,
        "Submitted",
        "2026-07-01T09:15:00+00:00",
    )

    assert claim.claim_number == "CLM-100101"
    assert claim.notes == ""
    assert claim.member_id == ""


def test_claim_carries_a_member_when_one_is_supplied():
    claim = Claim(
        "CLM-100102",
        "MS-1001",
        "Dental Recall",
        180.00,
        "Submitted",
        "2026-07-01T09:20:00+00:00",
        "Routine cleaning",
        "PM-4401",
    )

    assert claim.notes == "Routine cleaning"
    assert claim.member_id == "PM-4401"


# --- PlanMember and Amendment ----------------------------------------------


def test_plan_member_defaults_to_active():
    member = PlanMember("PM-4401", "MS-1001", "Jordan Avery", 2, "2024-04-01")
    assert member.status == "Active"
    assert member.dependents == 2


def test_amendment_requires_its_effective_date_and_contact_details():
    """An amendment is a *request* against an in-force contract.

    The effective date and a contact route are what make it actionable by plan
    administration, so none of them may quietly default to empty.
    """
    with pytest.raises(TypeError):
        Amendment("AMD-1", "MS-1001", "Plan Tier Change", "Move to Premium")  # type: ignore[call-arg]


def test_amendment_round_trips_its_fields():
    amendment = Amendment(
        "AMD-2001",
        "MS-1001",
        "Dependent Add",
        "Add spouse effective 1 September",
        "2026-09-01",
        "416-555-0142",
        "admin@northwind.example",
        "2026-07-02T11:00:00+00:00",
    )

    assert amendment.effective_date == "2026-09-01"
    assert amendment.contact_email == "admin@northwind.example"
    assert amendment.requested_change.startswith("Add spouse")
