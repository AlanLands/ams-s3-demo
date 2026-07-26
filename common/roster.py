"""The fictional engineer roster and the console's login credential check.

This is the whole of the shared auth story: who can log in, which assignment
group they belong to, and whether a submitted passcode matches. `api/auth.py`
wraps it for the React console; nothing else consumes it.

Roster and passcodes are fictional (CLAUDE.md hard rule #2) — not a real auth
backend, no stored credentials file, nothing to rotate. The passcode scheme is
deliberately simple and presenter-memorable: each engineer's passcode is
`1001 + their position in the flattened ENGINEERS_BY_GROUP roster` (so Ravi
Kumar/first entry -> 1001, next -> 1002, and so on); the one "Manager" account
is fixed at 9000.
"""

from __future__ import annotations

from dataclasses import dataclass

from common.constants import ASSIGNMENT_GROUPS

# Two engineers per assignment group so any group resolves to a real roster.
ENGINEERS_BY_GROUP: dict[str, list[str]] = {
    "App Support — PolicyCore": ["Ravi Kumar", "Elena Cruz"],
    "App Support — ClaimsPortal": ["Priya Nair", "Tom Becker"],
    "App Support — BillingGateway": ["Sam Patel", "Grace Liu"],
    "App Support — DocumentHub": ["Noah Bennett", "Aisha Khan"],
    "Batch Ops": ["Jordan Blake", "Meera Iyer"],
    "Integration Support": ["Diego Ramos", "Hana Suzuki"],
    "Service Desk L1": ["Alex Morgan", "Priti Rao"],
}
assert set(ENGINEERS_BY_GROUP) == set(ASSIGNMENT_GROUPS)

MANAGER_NAME = "Manager"

ROSTER: list[str] = [name for names in ENGINEERS_BY_GROUP.values() for name in names]

PASSCODE_BY_NAME: dict[str, str] = {name: str(1001 + i) for i, name in enumerate(ROSTER)}
PASSCODE_BY_NAME[MANAGER_NAME] = "9000"


@dataclass(frozen=True)
class Identity:
    name: str
    role: str  # "engineer" | "manager"
    group: str | None


def authenticate(name: str, passcode: str) -> bool:
    return name in PASSCODE_BY_NAME and PASSCODE_BY_NAME[name] == passcode.strip()


def group_for_engineer(engineer: str) -> str | None:
    for group, roster in ENGINEERS_BY_GROUP.items():
        if engineer in roster:
            return group
    return None
