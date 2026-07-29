"""Pre-existing regression suite for the PolicyCore app.

This file is **not** generated. It is checked in, it predates every S3 change
request, and no target's `testgen_allowlist` names it — the AI can neither
write it nor overwrite it. That is the entire point: every CR in this console
ends with an acceptance criterion of the form

    "Existing policy list, policy detail, claim submission, and claim list
     flows are unaffected."

and until this file existed, nothing in the pipeline verified that. The
generated suite proves the *new* behaviour; this one proves the old behaviour
survived it.

Two rules for anything added here:

1. **It must pass before and after every CR.** These are invariants, not
   assertions about the change under test. A test that only passes on the
   pre-CR baseline is a broken regression test, not a caught regression.
2. **It must not live under a target root.** `relevance.py::discover_mockapp_files`
   rglobs `*.py`/`*.java` under each target's root, so a file placed under
   `apps/policycore/` would join the codegen candidate pool, reshuffle the
   relevance funnel, and desync the committed replay recordings. Top-level
   `tests/` is outside every target root — keep it that way.

Deliberately excluded: anything touching `coverage_tier` upgrades
(CR-2026-041) or endorsement `priority` (CR-2026-042). Those are the changes
under test, and they belong in the generated suites.
"""

from __future__ import annotations

import pytest

from apps.policycore.core.claims import submit_claim
from apps.policycore.core.db import (
    get_policy,
    list_claims,
    list_endorsements,
    list_policies,
)
from apps.policycore.core.endorsements import submit_endorsement
from apps.policycore.core.seed import reseed

# Facts about the synthetic seed data (apps/policycore/core/seed.py) that the
# assertions below lean on. Pinned here so a seed change fails loudly in one
# place instead of subtly skewing several tests.
SEEDED_POLICY_COUNT = 18
SEEDED_CLAIM_COUNT = 6
KNOWN_POLICY = "POL-10001"
KNOWN_POLICY_HOLDER = "Maria Torres"
KNOWN_POLICY_PREMIUM = 812.50
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
    that drops or renames one breaks the portal's policy table."""
    for policy in list_policies():
        assert policy.policy_number.startswith("POL-")
        assert policy.holder_name
        assert policy.product_type in {"Auto", "Home", "Life"}
        assert isinstance(policy.premium, float)
        assert policy.premium > 0
        assert policy.status in {"Active", "Lapsed", "Cancelled"}


def test_policy_list_includes_non_active_policies() -> None:
    """The list is unfiltered — lapsed and cancelled policies still appear."""
    statuses = {p.status for p in list_policies()}
    assert {"Active", "Lapsed", "Cancelled"} <= statuses


# --- Policy detail flow -----------------------------------------------------


def test_policy_detail_returns_the_requested_policy() -> None:
    policy = get_policy(KNOWN_POLICY)
    assert policy is not None
    assert policy.policy_number == KNOWN_POLICY
    assert policy.holder_name == KNOWN_POLICY_HOLDER
    assert policy.product_type == "Auto"
    assert policy.premium == KNOWN_POLICY_PREMIUM
    assert policy.status == "Active"


def test_policy_detail_for_unknown_policy_returns_none() -> None:
    """Not an exception — the portal renders a "not found" message off None."""
    assert get_policy(UNKNOWN_POLICY) is None


# --- Claim submission flow --------------------------------------------------


def test_claim_submission_persists_and_defaults_to_submitted() -> None:
    claim = submit_claim(KNOWN_POLICY, "Collision", 1450.00, notes="Regression check")

    assert claim.policy_number == KNOWN_POLICY
    assert claim.claim_type == "Collision"
    assert claim.amount == 1450.00
    assert claim.status == "Submitted"
    assert claim.notes == "Regression check"
    assert claim.claim_number.startswith("CLM-")
    assert claim.filed_at  # ISO timestamp, set by the app not the caller

    stored = [c for c in list_claims(KNOWN_POLICY) if c.claim_number == claim.claim_number]
    assert len(stored) == 1
    assert stored[0].amount == 1450.00


def test_claim_submission_defaults_notes_to_empty() -> None:
    claim = submit_claim(KNOWN_POLICY, "Windshield", 320.00)
    assert claim.notes == ""


def test_two_claims_on_one_policy_get_distinct_numbers() -> None:
    first = submit_claim(KNOWN_POLICY, "Collision", 900.00)
    second = submit_claim(KNOWN_POLICY, "Theft", 1200.00)
    assert first.claim_number != second.claim_number


def test_claim_can_be_filed_against_a_lapsed_policy() -> None:
    """PolicyCore does not gate submission on policy status — adjusters
    triage that downstream. Pinned because it is easy to "fix" by accident."""
    claim = submit_claim(LAPSED_POLICY, "Collision", 500.00)
    assert claim.status == "Submitted"


# --- Claim list flow --------------------------------------------------------


def test_claim_list_returns_seeded_claims_for_a_policy() -> None:
    claims = list_claims(KNOWN_POLICY)
    assert [c.claim_number for c in claims] == ["CLM-50001"]
    assert claims[0].claim_type == "Collision"
    assert claims[0].status == "Approved"


def test_claim_list_is_scoped_to_one_policy() -> None:
    submit_claim(KNOWN_POLICY, "Collision", 100.00)
    assert all(c.policy_number == KNOWN_POLICY for c in list_claims(KNOWN_POLICY))
    assert list_claims("POL-10003") == []


def test_claim_list_totals_match_the_seed() -> None:
    total = sum(len(list_claims(p.policy_number)) for p in list_policies())
    assert total == SEEDED_CLAIM_COUNT


# --- Endorsement submission flow -------------------------------------------


def test_endorsement_submission_with_the_original_field_set_still_succeeds() -> None:
    """CR-2026-042 adds a sixth form field with a default. This call uses the
    pre-CR argument list verbatim and must keep working untouched — it is the
    executable form of that CR's "submitting without changing the priority
    still succeeds exactly as before" criterion."""
    endorsement = submit_endorsement(
        KNOWN_POLICY,
        "Address Change",
        "Update mailing address to 44 Rosewood Ave",
        "2026-09-01",
        "555-0142",
        "policyholder@example.invalid",
    )

    assert endorsement.policy_number == KNOWN_POLICY
    assert endorsement.endorsement_type == "Address Change"
    assert endorsement.requested_change == "Update mailing address to 44 Rosewood Ave"
    assert endorsement.effective_date == "2026-09-01"
    assert endorsement.contact_phone == "555-0142"
    assert endorsement.contact_email == "policyholder@example.invalid"
    assert endorsement.endorsement_number.startswith("END-")
    assert endorsement.filed_at


def test_endorsement_round_trips_through_the_list_view() -> None:
    submit_endorsement(
        KNOWN_POLICY,
        "Name Correction",
        "Correct surname spelling",
        "2026-10-15",
        "555-0177",
        "holder@example.invalid",
    )

    stored = list_endorsements(KNOWN_POLICY)
    assert len(stored) == 1
    assert stored[0].endorsement_type == "Name Correction"
    assert stored[0].contact_email == "holder@example.invalid"


def test_endorsement_list_is_empty_for_a_policy_with_none() -> None:
    assert list_endorsements("POL-10003") == []
