"""Unit tests for ClaimsPortal's inter-service contract.

Claims-Service reaches Policy-Service over HTTP, and everything about how it
finds and reads that service is worth pinning at unit level: the base URL comes
from the environment rather than a literal, and a contract that does not exist
is a `None`, not an exception.

`test_regression_claimsportal.py` covers the adjudication flow end to end.
This file covers the seams underneath it, so a failure names the seam.

Every assertion holds before and after US-2026-043. The user story adds deductible
handling to claim validation; nothing here asserts validation rules or the
absence of any field. The pydantic models are asserted through construction
and field access, so a user story that *adds* a field does not fail these tests.

Lives in `tests/`, not under `repos/claimsportal/` — same reason as the other
suites: a `.py` under a target root joins the codegen candidate pool.
"""

from __future__ import annotations

import importlib

import httpx
import pytest
from pydantic import BaseModel

from repos.claimsportal.claims_service import policy_client
from repos.claimsportal.claims_service.claim import Claim
from repos.claimsportal.policy_service.policy import Policy

# --- building payloads that survive a user story adding a required field -------------


def _payload_for(model: type[BaseModel], **overrides: object) -> dict:
    """A valid payload for `model`, whatever fields it currently declares.

    Hard-coding the baseline field set is what a construction-based test gets
    wrong: US-2026-043 adds `deductible` to the contract and `payableAmount` to
    the claim as *required* fields, and a test that constructs from the
    pre-user story set then fails on exactly the change it was supposed to be
    indifferent to. These suites are invariants — they must hold before and
    after every user story — so the payload is derived from the model rather than
    frozen, and the test asserts only the fields it actually cares about.
    """
    filler: dict[str, object] = {}
    for name, field in model.model_fields.items():
        if name in overrides:
            continue
        annotation = field.annotation
        if annotation is float:
            filler[name] = 0.0
        elif annotation is int:
            filler[name] = 0
        elif annotation is bool:
            filler[name] = False
        else:
            filler[name] = "x"
    return {**filler, **overrides}


# --- the service URL comes from the environment -----------------------------


def test_policy_service_url_defaults_to_localhost(monkeypatch):
    """Unset environment falls back to the local pair's port.

    The default is what makes a plain developer checkout run with no
    configuration; the override below is what makes it deployable.
    """
    monkeypatch.delenv("POLICY_SERVICE_URL", raising=False)
    reloaded = importlib.reload(policy_client)
    try:
        assert reloaded.POLICY_SERVICE_URL == "http://localhost:8081"
    finally:
        monkeypatch.delenv("POLICY_SERVICE_URL", raising=False)
        importlib.reload(policy_client)


def test_policy_service_url_is_taken_from_the_environment(monkeypatch):
    """No host or port is baked into the client.

    This is the property that lets the two services move to another host or
    to the 20111-20115 block without a code change.
    """
    monkeypatch.setenv("POLICY_SERVICE_URL", "http://policy-service.internal:20113")
    reloaded = importlib.reload(policy_client)
    try:
        assert reloaded.POLICY_SERVICE_URL == "http://policy-service.internal:20113"
    finally:
        monkeypatch.delenv("POLICY_SERVICE_URL", raising=False)
        importlib.reload(policy_client)


def test_the_module_reads_the_environment_at_import_time(monkeypatch):
    """Documents a real constraint rather than asserting a preference.

    `POLICY_SERVICE_URL` is bound once, at module import. The launch scripts
    source `.env` before exec'ing uvicorn, so this holds in practice — but a
    caller that sets the variable after import will not be honoured, and that
    is worth knowing before someone debugs it at 2am.
    """
    monkeypatch.setenv("POLICY_SERVICE_URL", "http://set-too-late.internal:9999")
    # No reload: the module was imported before this variable was set.
    assert policy_client.POLICY_SERVICE_URL != "http://set-too-late.internal:9999"


# --- find_policy: a missing contract is None, not an exception --------------


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"{self.status_code}", request=None, response=None  # type: ignore[arg-type]
            )


def test_find_policy_returns_none_for_an_unknown_contract(monkeypatch):
    """404 is an answer, not a failure.

    Claim intake asks "does this contract exist" and needs to reject the claim
    cleanly when it does not. Raising here would turn a routine rejection into
    a 500.
    """
    monkeypatch.setattr(policy_client.httpx, "get", lambda *a, **k: _FakeResponse(404))
    assert policy_client.find_policy("MS-0000") is None


def test_find_policy_returns_the_contract_view_when_it_exists(monkeypatch):
    payload = _payload_for(
        policy_client.PolicyView, policyNumber="MS-1001", annualMaximum=5000.0
    )
    monkeypatch.setattr(policy_client.httpx, "get", lambda *a, **k: _FakeResponse(200, payload))

    view = policy_client.find_policy("MS-1001")

    assert view is not None
    assert view.policyNumber == "MS-1001"
    assert view.annualMaximum == 5000.0


def test_find_policy_propagates_a_server_error(monkeypatch):
    """A 500 from Policy-Service is not "contract not found".

    Collapsing the two would let an outage read as a rejected claim, which is
    the failure mode the None-for-404 branch above must not be widened into.
    """
    monkeypatch.setattr(policy_client.httpx, "get", lambda *a, **k: _FakeResponse(503))
    with pytest.raises(httpx.HTTPStatusError):
        policy_client.find_policy("MS-1001")


# --- the published field names ----------------------------------------------


def test_policy_carries_the_published_contract_fields():
    # These names are a published API contract that US-2026-043 and the
    # committed recording depend on by exact spelling.
    for name in ("policyNumber", "holderName", "product", "status", "annualMaximum"):
        assert name in Policy.model_fields, f"published field {name} disappeared"

    policy = Policy(**_payload_for(Policy, policyNumber="MS-1001", annualMaximum=5000.0))
    assert policy.policyNumber == "MS-1001"
    assert policy.annualMaximum == 5000.0


def test_policy_rejects_a_missing_required_field():
    payload = _payload_for(Policy)
    payload.pop("policyNumber")
    with pytest.raises(Exception):  # pydantic ValidationError
        Policy(**payload)


def test_claim_carries_the_published_claim_fields():
    for name in ("id", "policyNumber", "holderName", "memberId", "serviceType",
                 "amount", "description", "status", "submittedAt"):
        assert name in Claim.model_fields, f"published field {name} disappeared"

    claim = Claim(**_payload_for(Claim, memberId="PM-4401", status="ACCEPTED"))
    assert claim.memberId == "PM-4401"
    assert claim.status == "ACCEPTED"


def test_claim_amount_accepts_an_integer_as_a_float():
    # Form posts arrive as JSON numbers; an integer amount must not be a
    # validation failure.
    claim = Claim(**_payload_for(Claim, amount=200))
    assert isinstance(claim.amount, float)
    assert claim.amount == 200.0
