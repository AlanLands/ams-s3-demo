"""Seed script for the MapleSure group benefits mock app.

Populates data/mockapp.db with synthetic group contracts, the plan members
enrolled under them, and a handful of existing benefit claims. All sponsors
and members below are fake/synthetic — never real people or companies.

Group contracts are held by the *employer*, so several rows can share one
holder_name: an employer typically buys health, dental and life as separate
contracts under one benefits programme.

Run as:
    python -m apps.policycore.core.seed
"""

from __future__ import annotations

from apps.policycore.core.db import (
    init_db,
    insert_claim,
    insert_plan_member,
    insert_policy,
    wipe_db,
)
from apps.policycore.core.models import Claim, PlanMember, Policy

# Synthetic plan sponsors only — no real people or companies.
_POLICIES: list[Policy] = [
    Policy("POL-10001", "Northwind Logistics Ltd.", "Health", 4820.50, "2023-02-14", "Active"),
    Policy("POL-10002", "Northwind Logistics Ltd.", "Dental", 1940.00, "2023-02-14", "Active"),
    Policy("POL-10003", "Northwind Logistics Ltd.", "Group Life", 1120.00, "2023-02-14", "Active"),
    Policy("POL-10004", "Cedarline Manufacturing Inc.", "Health", 7355.25, "2022-11-01", "Active"),
    Policy(
        "POL-10005", "Cedarline Manufacturing Inc.", "Disability", 3180.75, "2022-11-01", "Active"
    ),
    Policy("POL-10006", "Cedarline Manufacturing Inc.", "Dental", 2430.00, "2022-11-01", "Lapsed"),
    Policy("POL-10007", "Harbourview Health Group", "Health", 9512.40, "2021-06-20", "Active"),
    Policy(
        "POL-10008", "Harbourview Health Group", "Critical Illness", 1890.00, "2021-06-20", "Active"
    ),
    Policy("POL-10009", "Quill & Fenwick LLP", "Health", 2688.90, "2024-01-09", "Active"),
    Policy("POL-10010", "Quill & Fenwick LLP", "Group Life", 705.00, "2024-01-09", "Terminated"),
    Policy("POL-10011", "Bramford Municipal Services", "Health", 11799.99, "2020-09-30", "Active"),
    Policy("POL-10012", "Bramford Municipal Services", "Dental", 4555.30, "2020-09-30", "Active"),
    Policy(
        "POL-10013", "Bramford Municipal Services", "Disability", 5480.00, "2020-09-30", "Active"
    ),
    Policy("POL-10014", "Talus Software Co.", "Health", 3910.15, "2024-06-03", "Active"),
    Policy(
        "POL-10015", "Talus Software Co.", "Critical Illness", 1380.60, "2024-06-03", "Lapsed"
    ),
    Policy("POL-10016", "Rosebank Grocers Ltd.", "Health", 6845.00, "2023-01-25", "Active"),
    Policy("POL-10017", "Rosebank Grocers Ltd.", "Dental", 2622.75, "2023-01-25", "Active"),
    Policy("POL-10018", "Rosebank Grocers Ltd.", "Group Life", 1499.00, "2023-01-25", "Active"),
]

# Employees enrolled under those contracts. Synthetic names only.
_MEMBERS: list[PlanMember] = [
    PlanMember("MBR-30001", "POL-10001", "Maria Torres", 2, "2023-03-01"),
    PlanMember("MBR-30002", "POL-10001", "James Okafor", 0, "2023-03-01"),
    PlanMember("MBR-30003", "POL-10001", "Linh Nguyen", 3, "2023-06-15"),
    PlanMember("MBR-30004", "POL-10002", "Maria Torres", 2, "2023-03-01"),
    PlanMember("MBR-30005", "POL-10004", "Devon Marshall", 1, "2022-12-01"),
    PlanMember("MBR-30006", "POL-10005", "Priya Sharma", 0, "2022-12-01"),
    PlanMember("MBR-30007", "POL-10007", "Carlos Mendez", 4, "2021-07-01"),
    PlanMember("MBR-30008", "POL-10009", "Emily Chastain", 1, "2024-02-01"),
    PlanMember("MBR-30009", "POL-10011", "Tobias Reinholt", 2, "2020-10-15"),
    PlanMember("MBR-30010", "POL-10012", "Aaliyah Brooks", 0, "2020-10-15"),
    PlanMember("MBR-30011", "POL-10014", "Kenji Watanabe", 2, "2024-06-20"),
    PlanMember("MBR-30012", "POL-10016", "Sofia Alvarez", 3, "2023-02-10"),
    PlanMember("MBR-30013", "POL-10001", "Grace Kim", 0, "2024-01-08", "Terminated"),
]

# A handful of pre-existing benefit claims against a subset of the contracts above.
_CLAIMS: list[Claim] = [
    Claim(
        "CLM-50001",
        "POL-10001",
        "Paramedical",
        1240.00,
        "Approved",
        "2024-03-02T09:15:00",
        "Physiotherapy, 12 sessions. Paid to the plan's annual paramedical maximum.",
        "MBR-30001",
    ),
    Claim(
        "CLM-50002",
        "POL-10002",
        "Major Restorative",
        2310.50,
        "Under Review",
        "2024-05-19T14:40:00",
        "Crown and bridge work. Awaiting pre-determination from the dental office.",
        "MBR-30004",
    ),
    Claim(
        "CLM-50003",
        "POL-10005",
        "Short-Term Disability",
        4820.00,
        "Approved",
        "2023-12-08T11:00:00",
        "Eight-week absence. Attending physician's statement on file.",
        "MBR-30006",
    ),
    Claim(
        "CLM-50004",
        "POL-10009",
        "Prescription Drug",
        385.00,
        "Denied",
        "2024-02-14T16:22:00",
        "Denied — drug is not on the plan's formulary; a generic alternative is eligible.",
        "MBR-30008",
    ),
    Claim(
        "CLM-50005",
        "POL-10011",
        "Vision",
        410.00,
        "Approved",
        "2024-07-01T08:05:00",
        "Prescription eyewear. Paid to the 24-month vision maximum.",
        "MBR-30009",
    ),
    Claim(
        "CLM-50006",
        "POL-10014",
        "Dental Recall",
        186.75,
        "Submitted",
        "2024-07-10T13:30:00",
        "Routine recall exam and cleaning. Coordination of benefits pending.",
        "MBR-30011",
    ),
]


def reseed() -> None:
    """Wipe the mock app database and repopulate it with synthetic data."""
    wipe_db()
    init_db()
    for policy in _POLICIES:
        insert_policy(policy)
    for member in _MEMBERS:
        insert_plan_member(member)
    for claim in _CLAIMS:
        insert_claim(claim)


def main() -> None:
    reseed()
    print(
        f"Seeded {len(_POLICIES)} group contracts, {len(_MEMBERS)} plan members "
        f"and {len(_CLAIMS)} claims into data/mockapp.db"
    )


if __name__ == "__main__":
    main()
