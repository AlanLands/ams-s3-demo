from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from apps.claimsportal.policy_service.policy import Policy

app = FastAPI(title="policy-service")

STATIC_DIR = Path(__file__).resolve().parent / "static"

# Synthetic demo data only.
POLICIES: list[Policy] = [
    Policy(
        policyNumber="MS-1001",
        holderName="Avery Chen",
        product="Auto",
        status="ACTIVE",
        coverageLimit=25000,
    ),
    Policy(
        policyNumber="MS-1002",
        holderName="Jordan Patel",
        product="Home",
        status="ACTIVE",
        coverageLimit=500000,
    ),
    Policy(
        policyNumber="MS-1003",
        holderName="Sam Okafor",
        product="Auto",
        status="LAPSED",
        coverageLimit=15000,
    ),
    Policy(
        policyNumber="MS-1004",
        holderName="Riley Tremblay",
        product="Travel",
        status="ACTIVE",
        coverageLimit=10000,
    ),
]
BY_NUMBER: dict[str, Policy] = {p.policyNumber: p for p in POLICIES}


@app.get("/api/policies")
def list_policies() -> list[Policy]:
    return POLICIES


@app.get("/api/policies/{policy_number}")
def get_policy(policy_number: str) -> Policy:
    policy = BY_NUMBER.get(policy_number)
    if policy is None:
        raise HTTPException(status_code=404)
    return policy


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
