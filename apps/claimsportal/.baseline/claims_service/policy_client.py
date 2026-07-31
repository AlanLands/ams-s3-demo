from __future__ import annotations

import os

import httpx
from pydantic import BaseModel

POLICY_SERVICE_URL = os.getenv("POLICY_SERVICE_URL", "http://localhost:8081")


class PolicyView(BaseModel):
    """The subset of a group contract the claims service needs at intake."""

    policyNumber: str
    holderName: str
    product: str
    status: str
    annualMaximum: float


def list_policies() -> list[PolicyView]:
    response = httpx.get(f"{POLICY_SERVICE_URL}/api/policies", timeout=5.0)
    response.raise_for_status()
    return [PolicyView(**item) for item in response.json()]


def find_policy(policy_number: str) -> PolicyView | None:
    response = httpx.get(f"{POLICY_SERVICE_URL}/api/policies/{policy_number}", timeout=5.0)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return PolicyView(**response.json())
