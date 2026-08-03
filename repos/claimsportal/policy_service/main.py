from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from repos.claimsportal.policy_service.policy import Policy

app = FastAPI(title="policy-service")

STATIC_DIR = Path(__file__).resolve().parent / "static"

# Synthetic demo data only — plan sponsors are fictional employers.
POLICIES: list[Policy] = [
    Policy(
        policyNumber="MS-1001",
        holderName="Northwind Logistics Ltd.",
        product="Health",
        status="ACTIVE",
        annualMaximum=25000,
    ),
    Policy(
        policyNumber="MS-1002",
        holderName="Cedarline Manufacturing Inc.",
        product="Dental",
        status="ACTIVE",
        annualMaximum=5000,
    ),
    Policy(
        policyNumber="MS-1003",
        holderName="Quill & Fenwick LLP",
        product="Health",
        status="LAPSED",
        annualMaximum=15000,
    ),
    Policy(
        policyNumber="MS-1004",
        holderName="Talus Software Co.",
        product="Critical Illness",
        status="ACTIVE",
        annualMaximum=10000,
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
