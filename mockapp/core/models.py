"""Data models for the MapleSure policy/claims mock app.

Plain dataclasses only — no persistence or business logic here. Storage lives
in mockapp/core/db.py.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Policy:
    policy_number: str
    holder_name: str
    product_type: str  # "Auto" | "Home" | "Life"
    premium: float
    start_date: str  # ISO date string, e.g. "2024-03-01"
    status: str  # "Active" | "Lapsed" | "Cancelled"
    coverage_tier: str = "Standard"

@dataclass
class Claim:
    claim_number: str
    policy_number: str
    claim_type: str
    amount: float
    status: str  # "Submitted" | "Under Review" | "Approved" | "Denied"
    filed_at: str  # ISO datetime string
    notes: str = ""

@dataclass
class Endorsement:
    endorsement_number: str
    policy_number: str
    endorsement_type: str  # "Coverage Detail Change" | "Address Change" | "Name Correction" | ...
    requested_change: str
    effective_date: str  # ISO date string, e.g. "2024-03-01"
    contact_phone: str
    contact_email: str
    filed_at: str  # ISO datetime string
    priority: str = "Standard"
