"""Data models for the MapleSure group benefits mock app.

MapleSure writes **group benefits**: an employer (the plan sponsor) holds the
group contract, and its employees enrol as plan members, optionally covering
dependents. So the policyholder on a Policy row is the *employer*, not an
individual — sponsor_name is the plan sponsor and product_type is the benefit
the contract provides.

Plain dataclasses only — no persistence or business logic here. Storage lives
in repos/policycore/core/db.py.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Policy:
    # Field order is pinned by repos/policycore/AGENTS.md: plan_tier stays
    # last with a default so seed.py's positional Policy(...) calls keep working.
    policy_number: str
    sponsor_name: str  # the plan sponsor (employer) holding the group contract
    product_type: str  # "Group Life" | "Health" | "Dental" | "Disability" | "Critical Illness"
    contribution: float  # monthly contribution billed to the plan sponsor
    start_date: str  # ISO date string, e.g. "2024-03-01"
    status: str  # "Active" | "Lapsed" | "Terminated"
    plan_tier: str = "Standard"


@dataclass
class PlanMember:
    """An employee enrolled under a plan sponsor's group contract.

    Members are who actually incur claims; the sponsor holds the contract.
    dependents counts the spouse/children covered alongside the member.
    """

    member_id: str
    policy_number: str
    member_name: str
    dependents: int
    enrolled_on: str  # ISO date string
    status: str = "Active"  # "Active" | "Terminated"


@dataclass
class Claim:
    claim_number: str
    policy_number: str
    claim_type: str  # service type, e.g. "Paramedical" | "Dental Recall" | "Vision"
    amount: float
    status: str  # "Submitted" | "Under Review" | "Approved" | "Denied"
    filed_at: str  # ISO datetime string
    notes: str = ""
    # Last with a default: pre-existing positional submit_claim() call sites
    # predate the plan-member layer and must keep working unmodified.
    member_id: str = ""


@dataclass
class Amendment:
    amendment_number: str
    policy_number: str
    amendment_type: str  # "Plan Tier Change" | "Dependent Add" | "Address Change" | ...
    requested_change: str
    effective_date: str  # ISO date string, e.g. "2024-03-01"
    contact_phone: str
    contact_email: str
    filed_at: str  # ISO datetime string
