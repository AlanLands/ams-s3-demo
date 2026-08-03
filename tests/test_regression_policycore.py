"""Pre-existing regression suite for the PolicyCore app.

This file is **not** generated. It is checked in, it predates every S3 change
request, and no target's `testgen_allowlist` names it — the AI can neither
write it nor overwrite it. That is the entire point: every CR in this console
ends with an acceptance criterion of the form

    "Existing contract list, contract detail, plan-member roster, claim
     submission, and claim list flows are unaffected."

and until this file existed, nothing in the pipeline verified that. The
generated suite proves the *new* behaviour; this one proves the old behaviour
survived it.

Two rules for anything added here:

1. **It must pass before and after every CR.** These are invariants, not
   assertions about the change under test. A test that only passes on the
   pre-CR baseline is a broken regression test, not a caught regression.
2. **It must not live under a target root.** `relevance.py::discover_mockapp_files`
   rglobs `*.py`/`*.java` under each target's root, so a file placed under
   `repos/policycore/` would join the codegen candidate pool, reshuffle the
   relevance funnel, and desync the committed replay recordings. Top-level
   `tests/` is outside every target root — keep it that way.

Deliberately excluded: anything touching `plan_tier` upgrades
(CR-2026-041) or amendment `priority` (CR-2026-042). Those are the changes
under test, and they belong in the generated suites.
"""

from __future__ import annotations

import pytest

from repos.policycore.core.amendments import submit_amendment
from repos.policycore.core.claims import submit_claim
from repos.policycore.core.db import (
    get_policy,
    list_amendments,
    list_claims,
    list_plan_members,
    list_policies,
)
from repos.policycore.core.seed import reseed

# Facts about the synthetic seed data (repos/policycore/core/seed.py) that the
# assertions below lean on. Pinned here so a seed change fails loudly in one
# place instead of subtly skewing several tests.
SEEDED_POLICY_COUNT = 18
SEEDED_MEMBER_COUNT = 13
SEEDED_CLAIM_COUNT = 6
KNOWN_POLICY = "POL-10001"
KNOWN_POLICY_SPONSOR = "Northwind Logistics Ltd."
KNOWN_POLICY_CONTRIBUTION = 4820.50
LAPSED_POLICY = "POL-10006"
UNKNOWN_POLICY = "POL-99999"


@pytest.fixture(autouse=True)
def _fresh_db() -> None:
    """Reset to the synthetic seed before every test, same contract the
    generated suites use — no test may depend on another's writes."""
    reseed()


# --- Policy list flow -------------------------------------------------------


def test_policy_list_returns_every_seeded_policy() -> None:
    policies = list_policies()
    assert len(policies) == SEEDED_POLICY_COUNT
    assert {p.policy_number for p in policies} == {
        f"POL-{10001 + offset}" for offset in range(SEEDED_POLICY_COUNT)
    }


def test_policy_list_preserves_core_fields() -> None:
    """The list view reads these six fields off every row; a schema change
    that drops or renames one breaks the portal's group contract table."""
    for policy in list_policies():
        assert policy.policy_number.startswith("POL-")
        assert policy.sponsor_name
        assert policy.product_type in {
            "Health",
            "Dental",
            "Group Life",
            "Disability",
            "Critical Illness",
        }
        assert isinstance(policy.contribution, float)
        assert policy.contribution > 0
        assert policy.status in {"Active", "Lapsed", "Terminated"}


def test_policy_list_includes_non_active_policies() -> None:
    """The list is unfiltered — lapsed and terminated contracts still appear."""
    statuses = {p.status for p in list_policies()}
    assert {"Active", "Lapsed", "Terminated"} <= statuses


# --- Policy detail flow -----------------------------------------------------


def test_policy_detail_returns_the_requested_policy() -> None:
    policy = get_policy(KNOWN_POLICY)
    assert policy is not None
    assert policy.policy_number == KNOWN_POLICY
    assert policy.sponsor_name == KNOWN_POLICY_SPONSOR
    assert policy.product_type == "Health"
    assert policy.contribution == KNOWN_POLICY_CONTRIBUTION
    assert policy.status == "Active"


def test_policy_detail_for_unknown_policy_returns_none() -> None:
    """Not an exception — the portal renders a "not found" message off None."""
    assert get_policy(UNKNOWN_POLICY) is None


# --- Claim submission flow --------------------------------------------------


def test_claim_submission_persists_and_defaults_to_submitted() -> None:
    claim = submit_claim(KNOWN_POLICY, "Paramedical", 1450.00, notes="Regression check")

    assert claim.policy_number == KNOWN_POLICY
    assert claim.claim_type == "Paramedical"
    assert claim.amount == 1450.00
    assert claim.status == "Submitted"
    assert claim.notes == "Regression check"
    assert claim.claim_number.startswith("CLM-")
    assert claim.filed_at  # ISO timestamp, set by the app not the caller

    stored = [c for c in list_claims(KNOWN_POLICY) if c.claim_number == claim.claim_number]
    assert len(stored) == 1
    assert stored[0].amount == 1450.00


def test_claim_submission_defaults_notes_to_empty() -> None:
    claim = submit_claim(KNOWN_POLICY, "Vision", 320.00)
    assert claim.notes == ""


def test_two_claims_on_one_policy_get_distinct_numbers() -> None:
    first = submit_claim(KNOWN_POLICY, "Paramedical", 900.00)
    second = submit_claim(KNOWN_POLICY, "Vision", 1200.00)
    assert first.claim_number != second.claim_number


def test_claim_can_be_filed_against_a_lapsed_policy() -> None:
    """PolicyCore does not gate submission on contract status — adjudicators
    triage that downstream. Pinned because it is easy to "fix" by accident."""
    claim = submit_claim(LAPSED_POLICY, "Paramedical", 500.00)
    assert claim.status == "Submitted"


# --- Claim list flow --------------------------------------------------------


def test_claim_list_returns_seeded_claims_for_a_policy() -> None:
    claims = list_claims(KNOWN_POLICY)
    assert [c.claim_number for c in claims] == ["CLM-50001"]
    assert claims[0].claim_type == "Paramedical"
    assert claims[0].status == "Approved"


def test_claim_list_is_scoped_to_one_policy() -> None:
    submit_claim(KNOWN_POLICY, "Paramedical", 100.00)
    assert all(c.policy_number == KNOWN_POLICY for c in list_claims(KNOWN_POLICY))
    assert list_claims("POL-10003") == []


def test_claim_list_totals_match_the_seed() -> None:
    total = sum(len(list_claims(p.policy_number)) for p in list_policies())
    assert total == SEEDED_CLAIM_COUNT


# --- Amendment submission flow ---------------------------------------------


def test_amendment_submission_with_the_original_field_set_still_succeeds() -> None:
    """CR-2026-042 adds a sixth form field with a default. This call uses the
    pre-CR argument list verbatim and must keep working untouched — it is the
    executable form of that CR's "submitting without changing the priority
    still succeeds exactly as before" criterion."""
    amendment = submit_amendment(
        KNOWN_POLICY,
        "Address Change",
        "Update mailing address to 44 Rosewood Ave",
        "2026-09-01",
        "555-0142",
        "sponsor@example.invalid",
    )

    assert amendment.policy_number == KNOWN_POLICY
    assert amendment.amendment_type == "Address Change"
    assert amendment.requested_change == "Update mailing address to 44 Rosewood Ave"
    assert amendment.effective_date == "2026-09-01"
    assert amendment.contact_phone == "555-0142"
    assert amendment.contact_email == "sponsor@example.invalid"
    assert amendment.amendment_number.startswith("AMD-")
    assert amendment.filed_at


def test_amendment_round_trips_through_the_list_view() -> None:
    submit_amendment(
        KNOWN_POLICY,
        "Name Correction",
        "Correct surname spelling",
        "2026-10-15",
        "555-0177",
        "sponsor@example.invalid",
    )

    stored = list_amendments(KNOWN_POLICY)
    assert len(stored) == 1
    assert stored[0].amendment_type == "Name Correction"
    assert stored[0].contact_email == "sponsor@example.invalid"


def test_amendment_list_is_empty_for_a_policy_with_none() -> None:
    assert list_amendments("POL-10003") == []


# --- Plan member roster flow ------------------------------------------------


def test_member_roster_returns_every_seeded_member() -> None:
    """The contract detail view renders the roster off this call; the totals
    are pinned so a seed change fails here rather than skewing the view."""
    total = sum(len(list_plan_members(p.policy_number)) for p in list_policies())
    assert total == SEEDED_MEMBER_COUNT


def test_member_roster_is_scoped_to_one_contract() -> None:
    members = list_plan_members(KNOWN_POLICY)
    assert [m.member_id for m in members] == [
        "MBR-30001",
        "MBR-30002",
        "MBR-30003",
        "MBR-30013",
    ]
    assert all(m.policy_number == KNOWN_POLICY for m in members)


def test_member_roster_preserves_core_fields() -> None:
    for member in list_plan_members(KNOWN_POLICY):
        assert member.member_id.startswith("MBR-")
        assert member.member_name
        assert isinstance(member.dependents, int)
        assert member.dependents >= 0
        assert member.status in {"Active", "Terminated"}


def test_member_roster_includes_terminated_members() -> None:
    """Unfiltered, same as the contract list — a terminated member stays on
    the roster so prior claims still resolve to a name."""
    statuses = {m.status for m in list_plan_members(KNOWN_POLICY)}
    assert {"Active", "Terminated"} <= statuses


def test_member_roster_is_empty_for_a_contract_with_no_enrolments() -> None:
    assert list_plan_members("POL-10003") == []
