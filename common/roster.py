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
#
# The PolicyCore list is six rather than two because it absorbed the
# ClaimsPortal group's members when that application was removed (2026-08-04).
# They were **appended in their original order, at the position the
# ClaimsPortal group used to occupy**, and that is load-bearing rather than
# tidy: passcodes are `1001 + position in the flattened roster`, so merging
# here keeps every passcode in the presenter notes pointing at the same person
# it did before — 1001 Ravi, 1003 Priya, 1004 Tom. Reordering this list
# renumbers everyone below it.
#
# Priya Nair and Tom Becker carry the `tester` role (TESTER_NAMES below), which
# is why the group needs builders of its own: `suggested_assignee` skips
# testers, and a team of nothing but testers suggests nobody at all.
#
# The group is also the right home on the merits, not just arithmetically:
# App Support — PolicyCore already owns EnrolDirect (see
# `s3_enhancement/applications.py`), so it is the surviving application-support
# team for the plan-administration estate.
ENGINEERS_BY_GROUP: dict[str, list[str]] = {
    "App Support — PolicyCore": [
        "Ravi Kumar",
        "Elena Cruz",
        "Priya Nair",
        "Tom Becker",
        "Arjun Mehta",
        "Clara Bishop",
    ],
    "App Support — BillingGateway": ["Sam Patel", "Grace Liu"],
    "App Support — DocumentHub": ["Noah Bennett", "Aisha Khan"],
    "Batch Ops": ["Jordan Blake", "Meera Iyer"],
    "Integration Support": ["Diego Ramos", "Hana Suzuki"],
    "Service Desk L1": ["Alex Morgan", "Priti Rao"],
}
assert set(ENGINEERS_BY_GROUP) == set(ASSIGNMENT_GROUPS)

MANAGER_NAME = "Manager"

# Who tests rather than builds. These two are already the QA hand-off roster the
# console offers on the design-doc stage, and the seeded board has Priya Nair
# holding AMS-101 at QA — so naming them here makes the role match the board
# that already exists rather than inventing a third set of people.
#
# They stay in ENGINEERS_BY_GROUP on purpose: that map is *group membership*,
# which drives routing and the group shown on their identity, and removing them
# would strand `group_for_engineer` and the seeded ticket. Role is an overlay on
# the roster, not a separate roster — see `role_for`.
TESTER_NAMES: frozenset[str] = frozenset({"Priya Nair", "Tom Becker"})

ROSTER: list[str] = [name for names in ENGINEERS_BY_GROUP.values() for name in names]

PASSCODE_BY_NAME: dict[str, str] = {name: str(1001 + i) for i, name in enumerate(ROSTER)}
PASSCODE_BY_NAME[MANAGER_NAME] = "9000"


@dataclass(frozen=True)
class Identity:
    name: str
    role: str  # "engineer" | "manager" | "tester"
    group: str | None


def role_for(name: str) -> str:
    """The console role a roster name logs in as.

    One place, so the API and anything else asking cannot disagree. The console
    uses this to decide which pipeline stages a person sees: a manager has no
    reason to read generated code or a test run, and a developer has no reason
    to drive the QA test bench.
    """
    if name == MANAGER_NAME:
        return "manager"
    if name in TESTER_NAMES:
        return "tester"
    return "engineer"


def is_tester(name: str) -> bool:
    return name in TESTER_NAMES


def authenticate(name: str, passcode: str) -> bool:
    return name in PASSCODE_BY_NAME and PASSCODE_BY_NAME[name] == passcode.strip()


def group_for_engineer(engineer: str) -> str | None:
    for group, roster in ENGINEERS_BY_GROUP.items():
        if engineer in roster:
            return group
    return None
