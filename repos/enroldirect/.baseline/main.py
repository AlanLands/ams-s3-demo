"""EnrolDirect — MapleSure's online enrolment channel.

Two surfaces, deliberately separated.

**The gate** (`/api/eligibility/...`) is the runtime: it answers whether one
applicant may use the self-serve channel on one contract, and it is the only
part a member ever touches.

**The analysis** (`/api/analysis/...`) reports which systems consume the
access preferences, how those preferences are configured across the book, and
what changes if the unclassified prospect population is treated as members
rather than guests. It exists because that question could not be answered from
the options' descriptions alone — it depended on configuration nobody had
counted.

Every analysis figure is computed from the seeded directory by pure functions
in `impact.py`. No model call, so nothing here can be confidently wrong in the
way generated prose can, and there is no cache to warm.

Runs on nothing but the venv (FastAPI + uvicorn, already pinned), so a
locked-down sandbox can host it.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from repos.enroldirect import benefits, directory, enrolments, impact
from repos.enroldirect.eligibility import check_eligibility
from repos.enroldirect.preferences import unknown_preferences

app = FastAPI(title="enroldirect")

STATIC_DIR = Path(__file__).resolve().parent / "static"


class EligibilityRequest(BaseModel):
    """An access check for one seeded applicant."""

    applicantId: str


def _contract_payload(contract: directory.GroupContract) -> dict[str, object]:
    """Serialise a contract, surfacing any preference this app cannot enforce.

    `unrecognisedPreferences` is normally empty. It is on the payload rather
    than logged because a contract configured in a newer PolicyCore release
    will still serve its known preferences correctly here, and the operator
    needs to see the gap without reading the service's logs.
    """
    return {
        "contractNumber": contract.contractNumber,
        "sponsorName": contract.sponsorName,
        "status": contract.status,
        "enabledPreferences": list(contract.enabledPreferences),
        "unrecognisedPreferences": list(
            unknown_preferences(contract.enabledPreferences)
        ),
    }


def _applicant_payload(applicant) -> dict[str, object]:
    return {
        "applicantId": applicant.applicantId,
        "fullName": applicant.fullName,
        "contractNumber": applicant.contractNumber,
        "category": applicant.category,
        "hasActiveBenefit": applicant.hasActiveBenefit,
    }


@app.get("/api/contracts")
def list_contracts() -> list[dict[str, object]]:
    return [_contract_payload(c) for c in directory.CONTRACTS]


@app.get("/api/contracts/{contract_number}")
def get_contract(contract_number: str) -> dict[str, object]:
    contract = directory.get_contract(contract_number)
    if contract is None:
        raise HTTPException(status_code=404, detail="contract not found")
    return _contract_payload(contract)


@app.get("/api/applicants")
def list_applicants() -> list[dict[str, object]]:
    return [_applicant_payload(a) for a in directory.APPLICANTS]


@app.get("/api/applicants/{applicant_id}")
def get_applicant(applicant_id: str) -> dict[str, object]:
    applicant = directory.get_applicant(applicant_id)
    if applicant is None:
        raise HTTPException(status_code=404, detail="applicant not found")
    return _applicant_payload(applicant)


@app.post("/api/eligibility/check")
def check(request: EligibilityRequest) -> dict[str, object]:
    """Run the access gate for one applicant."""
    applicant = directory.get_applicant(request.applicantId)
    if applicant is None:
        raise HTTPException(status_code=404, detail="applicant not found")
    contract = directory.get_contract(applicant.contractNumber)
    if contract is None:
        # The applicant references a contract the directory does not hold.
        # That is an upstream integrity fault, not a denial, and reporting it
        # as "access refused" would hide it from whoever has to fix it.
        raise HTTPException(
            status_code=502,
            detail=(
                f"applicant {applicant.applicantId} references unknown contract "
                f"{applicant.contractNumber}"
            ),
        )
    decision = check_eligibility(applicant, contract)

    return {
        "granted": decision.granted,
        "applicantId": decision.applicantId,
        "fullName": applicant.fullName,
        "contractNumber": decision.contractNumber,
        "sponsorName": contract.sponsorName,
        "category": decision.category,
        "requiredPreference": decision.requiredPreference,
        "authorisingPreference": decision.authorisingPreference,
        "reasons": decision.reasons,
    }


class EnrolmentRequest(BaseModel):
    """A submission against one plan at one coverage tier."""

    applicantId: str
    planCode: str
    coverageTier: str


def _plan_payload(plan: benefits.BenefitPlan) -> dict[str, object]:
    return {
        "planCode": plan.planCode,
        "contractNumber": plan.contractNumber,
        "name": plan.name,
        "category": plan.category,
        "memberOnly": plan.memberOnly,
        "offeredTiers": list(plan.offeredTiers),
        "monthlyPremium": plan.monthlyPremium,
    }


@app.get("/api/plans")
def list_plans() -> list[dict[str, object]]:
    return [_plan_payload(p) for p in benefits.PLANS]


@app.get("/api/contracts/{contract_number}/plans")
def plans_for_contract(contract_number: str) -> list[dict[str, object]]:
    if directory.get_contract(contract_number) is None:
        raise HTTPException(status_code=404, detail="contract not found")
    return [_plan_payload(p) for p in benefits.plans_for_contract(contract_number)]


@app.get("/api/applicants/{applicant_id}/plans")
def plans_open_to_applicant(applicant_id: str) -> dict[str, object]:
    """The catalogue as this applicant would see it.

    Plans the applicant cannot take are returned marked rather than filtered
    out. A plan that silently vanishes produces "why can't I see dental?"; a
    plan shown as unavailable with its reason does not.
    """
    applicant = directory.get_applicant(applicant_id)
    if applicant is None:
        raise HTTPException(status_code=404, detail="applicant not found")
    open_codes = {
        p.planCode
        for p in benefits.plans_open_to(applicant.contractNumber, applicant.category)
    }
    return {
        "applicantId": applicant.applicantId,
        "category": applicant.category,
        "plans": [
            {
                **_plan_payload(plan),
                "available": plan.planCode in open_codes,
                "unavailableReason": (
                    None
                    if plan.planCode in open_codes
                    else "Requires existing coverage under the contract."
                ),
            }
            for plan in benefits.plans_for_contract(applicant.contractNumber)
        ],
    }


@app.post("/api/enrolments")
def submit_enrolment(request: EnrolmentRequest) -> dict[str, object]:
    """Submit an enrolment.

    A refused enrolment is a 200 carrying a REFUSED record, not an HTTP error.
    The applicant asked a valid question and got a valid, recorded answer —
    turning "you may not enrol in this plan" into a 4xx would lose the audit
    entry that says so and why.
    """
    try:
        record = enrolments.submit(
            request.applicantId,
            request.planCode,
            request.coverageTier,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return record.as_dict()


@app.get("/api/enrolments")
def list_enrolments() -> list[dict[str, object]]:
    return [r.as_dict() for r in enrolments.all_records()]


@app.get("/api/enrolments/summary")
def enrolment_summary() -> dict[str, object]:
    return enrolments.summary()


@app.post("/api/enrolments/reset")
def reset_enrolments() -> dict[str, object]:
    """Clear the enrolment log so a rehearsal can be run twice."""
    enrolments.reset()
    return {"status": "reset", "totalAttempts": 0}


@app.get("/api/analysis/consumers")
def analysis_consumers() -> list[dict[str, object]]:
    return impact.consumers()


@app.get("/api/analysis/preference-usage")
def analysis_preference_usage() -> dict[str, object]:
    return {
        "preferences": impact.preference_usage(),
        "categories": impact.category_population(),
    }


@app.get("/api/analysis/prospect-impact")
def analysis_prospect_impact() -> dict[str, object]:
    return impact.prospect_impact()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
