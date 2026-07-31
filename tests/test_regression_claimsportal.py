"""Pre-existing regression suite for the ClaimsPortal contract lookup API.

Checked in, human-authored, and named by no target's testgen allowlist — S3
can neither write nor overwrite it. CR-2026-043 edits policy_service (it adds
a deductible to the group contract record), so "the existing contract lookup
is unaffected" is a claim that needs a test rather than a promise.

Two constraints keep this passing on both sides of the CR:

1. Assertions go through HTTP and read fields off JSON, not by constructing
   `Policy(...)` directly — the model gains a field in the CR, and a test
   that constructed one positionally would break the moment the change
   applied, which would look like a regression and be nothing of the sort.
2. Nothing here asserts the *absence* of fields. A new `deductible` key in
   the response is the CR doing its job; only a missing or altered
   pre-existing key is a regression.

Must pass before and after CR-2026-043, and must not live under
`apps/claimsportal/` — see the same two rules in
`tests/test_regression_policycore.py`.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from apps.claimsportal.policy_service.main import app

client = TestClient(app)

REQUIRED_FIELDS = ["policyNumber", "holderName", "product", "status", "annualMaximum"]


def test_contract_directory_lists_all_seeded_contracts():
    response = client.get("/api/policies")

    assert response.status_code == 200
    policies = response.json()
    assert isinstance(policies, list)
    assert len(policies) == 4
    assert [p["policyNumber"] for p in policies] == ["MS-1001", "MS-1002", "MS-1003", "MS-1004"]


def test_every_contract_exposes_the_fields_claims_service_reads():
    policies = client.get("/api/policies").json()
    assert policies

    for policy in policies:
        for field in REQUIRED_FIELDS:
            assert field in policy, f"policy {policy['policyNumber']} lost field {field}"


def test_single_contract_lookup_returns_the_known_record():
    response = client.get("/api/policies/MS-1001")

    assert response.status_code == 200
    policy = response.json()
    assert policy["policyNumber"] == "MS-1001"
    assert policy["holderName"] == "Northwind Logistics Ltd."
    assert policy["product"] == "Health"
    assert policy["status"] == "ACTIVE"
    assert policy["annualMaximum"] == 25000


def test_unknown_contract_still_returns_not_found():
    response = client.get("/api/policies/MS-9999")

    assert response.status_code == 404


def test_lapsed_contract_status_survives_the_round_trip():
    # claims_service rejects on this exact string; if the CR normalised or
    # re-cased status values, every lapsed-contract rejection would silently
    # turn into an acceptance.
    policy = client.get("/api/policies/MS-1003").json()

    assert policy["status"] == "LAPSED"
