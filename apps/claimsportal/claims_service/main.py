from __future__ import annotations

from datetime import UTC, datetime
from itertools import count
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from apps.claimsportal.claims_service import policy_client
from apps.claimsportal.claims_service.claim import Claim

app = FastAPI(title="claims-service")

STATIC_DIR = Path(__file__).resolve().parent / "static"

CLAIMS: list[Claim] = []
_next_id = count(1)


class ClaimRequest(BaseModel):
    policyNumber: str
    amount: float
    description: str


@app.get("/api/claims")
def list_claims() -> list[Claim]:
    return CLAIMS


# Live passthrough to policy-service so the claims UI can offer a policy picker.
@app.get("/api/claims/policy-directory")
def policy_directory() -> list[policy_client.PolicyView]:
    return policy_client.list_policies()


@app.post("/api/claims", status_code=201)
def submit_claim(request: ClaimRequest) -> Claim:
    policy = policy_client.find_policy(request.policyNumber)
    if policy is None:
        return JSONResponse(
            status_code=422, content={"error": f"Unknown policy: {request.policyNumber}"}
        )

    if policy.status != "ACTIVE":
        status = f"REJECTED_POLICY_{policy.status}"
    elif request.amount > policy.coverageLimit:
        status = "REJECTED_OVER_LIMIT"
    else:
        status = "ACCEPTED"

    claim = Claim(
        id=next(_next_id),
        policyNumber=policy.policyNumber,
        holderName=policy.holderName,
        amount=request.amount,
        description=request.description,
        status=status,
        submittedAt=datetime.now(UTC).isoformat(),
    )
    CLAIMS.append(claim)
    return claim


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
