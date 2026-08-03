"""The three console roles, and the one place that decides them.

The console hides pipeline stages per role: a manager has no reason to read
generated code or a test run, a developer does not drive the test bench that
independently checks their own change, and a tester does not get a Generate
stage — a tester who can regenerate the change under test is not an independent
check of it.

That split is presentation, not authorization: `stageAccess.ts` filters the
stage rail and the router redirects a typed-in URL, but the API does not
enforce it. What *is* worth pinning is the role assignment itself, because two
things depend on it agreeing with the seeded board and with the frontend's own
hand-off roster.
"""

from __future__ import annotations

from common.roster import (
    ENGINEERS_BY_GROUP,
    MANAGER_NAME,
    PASSCODE_BY_NAME,
    ROSTER,
    TESTER_NAMES,
    is_tester,
    role_for,
)
from s3_enhancement.routing import route_ticket


def test_manager_is_the_only_manager():
    assert role_for(MANAGER_NAME) == "manager"
    assert [name for name in ROSTER if role_for(name) == "manager"] == []


def test_testers_are_the_qa_handoff_pair():
    """These names must match the console's TESTER_ROSTER.

    `useS3Controller.ts` offers exactly these two on the design-doc stage's QA
    hand-off. If the two lists drift, the console hands a ticket to someone who
    then logs in without a Tests stage and cannot act on it.
    """
    assert TESTER_NAMES == frozenset({"Priya Nair", "Tom Becker"})
    for name in TESTER_NAMES:
        assert role_for(name) == "tester"
        assert is_tester(name)


def test_everyone_else_is_an_engineer():
    for name in ROSTER:
        if name in TESTER_NAMES:
            continue
        assert role_for(name) == "engineer", name


def test_testers_keep_their_group_membership():
    """Role is an overlay on the roster, not a separate roster.

    Testers stay in ENGINEERS_BY_GROUP because that map is group membership —
    it drives routing and the group shown on their identity, and the seeded
    board has a tester holding AMS-101. Removing them would strand both.
    """
    for name in TESTER_NAMES:
        assert name in ROSTER
        assert name in PASSCODE_BY_NAME


def test_every_group_can_still_supply_a_developer():
    """No team may be all testers.

    `RouteDecision.suggested_assignee` proposes who *builds* a change and skips
    testers. A group with no engineer left would suggest nobody, and the
    console would offer an empty assignee on a routed ticket.
    """
    for group, members in ENGINEERS_BY_GROUP.items():
        buildable = [name for name in members if not is_tester(name)]
        assert buildable, f"{group} has no non-tester member"


def test_suggested_assignee_never_proposes_a_tester():
    """The ClaimsPortal group is the case that regressed.

    Its roster is ["Priya Nair", "Tom Becker"] and both are testers' names in
    the frontend's hand-off list; before this, `suggested_assignee` returned
    roster[0] and would have proposed a tester as the developer.
    """
    decision = route_ticket(ci="ClaimsPortal")
    if decision.routed:
        assignee = decision.suggested_assignee
        assert assignee
        assert not is_tester(assignee), f"suggested a tester: {assignee}"


def test_unrouted_ticket_suggests_nobody():
    decision = route_ticket(ci="NoSuchApplication")
    assert decision.suggested_assignee == ""
