"""Seed script for the MapleSure policy/claims mock app.

Populates data/mockapp.db with synthetic policies and a handful of existing
claims. All names below are fake/synthetic — never real people or companies.

Run as:
    python -m apps.policycore.core.seed
"""

from __future__ import annotations

from apps.policycore.core.db import init_db, insert_claim, insert_policy, wipe_db
from apps.policycore.core.models import Claim, Policy

# Synthetic policyholders only — no real people or companies.
_POLICIES: list[Policy] = [
    Policy("POL-10001", "Maria Torres", "Auto", 812.50, "2023-02-14", "Active"),
    Policy("POL-10002", "James Okafor", "Home", 1420.00, "2022-11-01", "Active"),
    Policy("POL-10003", "Linh Nguyen", "Life", 640.00, "2021-06-20", "Active"),
    Policy("POL-10004", "Devon Marshall", "Auto", 955.25, "2024-01-09", "Active"),
    Policy("POL-10005", "Priya Sharma", "Home", 1685.75, "2020-09-30", "Active"),
    Policy("POL-10006", "Carlos Mendez", "Auto", 730.00, "2023-07-11", "Lapsed"),
    Policy("POL-10007", "Emily Chastain", "Life", 512.40, "2019-03-05", "Active"),
    Policy("POL-10008", "Tobias Reinholt", "Home", 1290.00, "2022-05-18", "Active"),
    Policy("POL-10009", "Aaliyah Brooks", "Auto", 888.90, "2024-04-22", "Active"),
    Policy("POL-10010", "Kenji Watanabe", "Life", 705.00, "2021-12-01", "Cancelled"),
    Policy("POL-10011", "Sofia Alvarez", "Auto", 799.99, "2023-10-16", "Active"),
    Policy("POL-10012", "Grace Kim", "Home", 1555.30, "2020-02-27", "Active"),
    Policy("POL-10013", "Nathaniel Bosch", "Life", 480.00, "2022-08-08", "Active"),
    Policy("POL-10014", "Fatima Rahman", "Auto", 910.15, "2024-06-03", "Active"),
    Policy("POL-10015", "Owen Whitfield", "Home", 1380.60, "2021-04-19", "Lapsed"),
    Policy("POL-10016", "Chloe Bennett", "Auto", 845.00, "2023-01-25", "Active"),
    Policy("POL-10017", "Marcus Delgado", "Life", 622.75, "2019-11-11", "Active"),
    Policy("POL-10018", "Ingrid Solheim", "Home", 1499.00, "2022-03-14", "Active"),
]

# A handful of pre-existing claims against a subset of the policies above.
_CLAIMS: list[Claim] = [
    Claim(
        "CLM-50001",
        "POL-10001",
        "Collision",
        3200.00,
        "Approved",
        "2024-03-02T09:15:00",
        "Rear-end collision, minor damage. Approved after adjuster review.",
    ),
    Claim(
        "CLM-50002",
        "POL-10002",
        "Water Damage",
        7800.50,
        "Under Review",
        "2024-05-19T14:40:00",
        "Basement flooding from burst pipe. Awaiting contractor estimate.",
    ),
    Claim(
        "CLM-50003",
        "POL-10005",
        "Fire Damage",
        15400.00,
        "Approved",
        "2023-12-08T11:00:00",
        "Kitchen fire, smoke damage throughout first floor.",
    ),
    Claim(
        "CLM-50004",
        "POL-10009",
        "Theft",
        1250.00,
        "Denied",
        "2024-02-14T16:22:00",
        "Claim denied — police report did not match policy vehicle.",
    ),
    Claim(
        "CLM-50005",
        "POL-10011",
        "Windshield",
        410.00,
        "Approved",
        "2024-07-01T08:05:00",
        "Cracked windshield from road debris. Fast-tracked, glass-only claim.",
    ),
    Claim(
        "CLM-50006",
        "POL-10014",
        "Collision",
        5600.75,
        "Submitted",
        "2024-07-10T13:30:00",
        "Multi-vehicle incident, damage assessment pending.",
    ),
]


def reseed() -> None:
    """Wipe the mock app database and repopulate it with synthetic data."""
    wipe_db()
    init_db()
    for policy in _POLICIES:
        insert_policy(policy)
    for claim in _CLAIMS:
        insert_claim(claim)


def main() -> None:
    reseed()
    print(
        f"Seeded {len(_POLICIES)} policies and {len(_CLAIMS)} claims "
        "into data/mockapp.db"
    )


if __name__ == "__main__":
    main()
