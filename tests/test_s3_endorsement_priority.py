import pytest
from apps.policycore.core.endorsements import submit_endorsement
from apps.policycore.core.db import list_endorsements
from apps.policycore.core.seed import reseed

@pytest.fixture(autouse=True)
def reseed_db():
    reseed()

POLICY_NUMBER = "POL-10001"


def test_default_priority_standard():
    endorsement = submit_endorsement(
        policy_number=POLICY_NUMBER,
        endorsement_type="Coverage Detail Change",
        requested_change="Increase coverage",
        effective_date="2025-01-01",
        contact_phone="123-456-7890",
        contact_email="policyholder@example.com"
    )
    assert endorsement.priority == "Standard"


def test_priority_urgent():
    endorsement = submit_endorsement(
        policy_number=POLICY_NUMBER,
        endorsement_type="Address Change",
        requested_change="Move to a new address",
        effective_date="2025-01-15",
        contact_phone="987-654-3210",
        contact_email="addresschange@example.com",
        priority="Urgent"
    )
    assert endorsement.priority == "Urgent"


def test_persisted_priority_round_trip():
    original_endorsement = submit_endorsement(
        policy_number=POLICY_NUMBER,
        endorsement_type="Name Correction",
        requested_change="Correct spelling",
        effective_date="2025-02-01",
        contact_phone="555-555-5555",
        contact_email="namecorrection@example.com",
        priority="Urgent"
    )
    endorsements = list_endorsements(POLICY_NUMBER)
    assert any(e.endorsement_number == original_endorsement.endorsement_number and e.priority == "Urgent" for e in endorsements)


def test_existing_fields_unaffected():
    endorsement = submit_endorsement(
        policy_number=POLICY_NUMBER,
        endorsement_type="Coverage Detail Change",
        requested_change="Add comprehensive coverage",
        effective_date="2025-03-01",
        contact_phone="111-222-3333",
        contact_email="coveragedetail@example.com"
    )
    assert endorsement.endorsement_type == "Coverage Detail Change"
    assert endorsement.requested_change == "Add comprehensive coverage"
    assert endorsement.effective_date == "2025-03-01"
    assert endorsement.contact_phone == "111-222-3333"
    assert endorsement.contact_email == "coveragedetail@example.com"
