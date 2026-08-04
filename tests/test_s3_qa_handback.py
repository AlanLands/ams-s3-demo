"""The QA fail path: who a ticket goes back to, and who is allowed to send it.

The rule under test is that the developer's name is *derived from the ticket's
own history*, never taken from the caller. A console that could name the
developer could name the wrong one, and the timeline would have no way to tell
— same reason the commit gate and the release record's approvals are read
server-side.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from apps.console.api.main import app
from apps.console.api.routers import s3 as s3_router
from common.jira_client import JiraError
from common.roster import PASSCODE_BY_NAME
from common.ticket_events import events_for, record_event
from s3_enhancement import qa_handback


def _assigned(name: str) -> dict:
    return {"action": "ticket_assigned", "detail": name}


def _client(name: str = "Priya Nair") -> TestClient:
    client = TestClient(app)
    response = client.post(
        "/api/auth/login", json={"name": name, "passcode": PASSCODE_BY_NAME[name]}
    )
    assert response.status_code == 200
    return client


@pytest.fixture(autouse=True)
def _isolated_events(tmp_path, monkeypatch):
    monkeypatch.setenv("TICKET_EVENTS_PATH", str(tmp_path / "ticket_events.jsonl"))


def test_previous_developer_is_the_last_non_tester_to_hold_the_ticket():
    """The ordinary round trip: story intake put it on Ravi, Ravi handed it to
    Priya for QA, Priya fails it. It goes back to Ravi."""
    events = [_assigned("Ravi Kumar"), _assigned("Priya Nair")]

    assert qa_handback.previous_developer(events, current_holder="Priya Nair") == "Ravi Kumar"


def test_previous_developer_skips_a_tester_to_tester_hand_off():
    """A second pair of eyes must not make the first tester "the developer" —
    the ticket goes back past both of them to whoever built the change."""
    events = [_assigned("Elena Cruz"), _assigned("Priya Nair"), _assigned("Tom Becker")]

    assert qa_handback.previous_developer(events, current_holder="Tom Becker") == "Elena Cruz"


def test_previous_developer_is_none_when_only_testers_ever_held_it():
    """A ticket a manager assigned straight to a tester has no developer to
    return to. None, not a guess — a guess puts someone's name on work they
    never touched."""
    events = [_assigned("Priya Nair")]

    assert qa_handback.previous_developer(events, current_holder="Priya Nair") is None


def test_previous_developer_reads_the_latest_holder_not_the_first():
    """After a manager reassigns, the ticket belongs to the new developer — a
    hand-back must follow the reassignment, not the original intake."""
    events = [_assigned("Ravi Kumar"), _assigned("Elena Cruz"), _assigned("Priya Nair")]

    assert qa_handback.previous_developer(events, current_holder="Priya Nair") == "Elena Cruz"


def test_failure_evidence_reports_the_red_suite_and_nothing_else():
    events = [
        {"action": "tests_failed", "detail": "3/7 passed", "ts": "2026-08-04 10:00:00"},
        {"action": "regression_passed", "detail": "12/12 passed", "ts": "2026-08-04 10:01:00"},
    ]

    assert qa_handback.failure_evidence(events) == "generated suite: 3/7 passed"


def test_failure_evidence_is_empty_when_every_suite_is_green():
    """A tester may fail a ticket on something no suite covers. The record says
    so rather than implying a red run that never happened."""
    events = [{"action": "tests_passed", "detail": "7/7 passed", "ts": "2026-08-04 10:00:00"}]

    assert qa_handback.failure_evidence(events) == ""


def test_return_to_developer_reassigns_moves_status_and_records_the_reason():
    record_event("AMS-1045", "system", "ticket_assigned", detail="Ravi Kumar")
    record_event("AMS-1045", "human", "ticket_assigned", detail="Priya Nair")
    record_event("AMS-1045", "ai", "tests_failed", detail="3/7 passed")

    jira = MagicMock()
    jira.get_issue.return_value = {"key": "AMS-1045", "assignee": "Priya Nair", "status": "QA"}
    jira.assign_issue.side_effect = lambda key, assignee: {"key": key, "assignee": assignee}
    jira.set_issue_status.side_effect = lambda key, status: {"key": key, "status": status}

    with patch.object(s3_router, "get_jira_client", return_value=jira):
        response = _client("Priya Nair").post(
            "/api/s3/jira/return-to-developer",
            json={"key": "AMS-1045", "reason": "Prospect on two contracts is still refused."},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["developer"] == "Ravi Kumar"
    assert body["issue"]["assignee"] == "Ravi Kumar"
    # In Progress, not To Do: the change exists and is being fixed.
    assert body["issue"]["status"] == "In Progress"
    assert body["evidence"] == "generated suite: 3/7 passed"
    jira.assign_issue.assert_called_once_with("AMS-1045", "Ravi Kumar")
    jira.set_issue_status.assert_called_once_with("AMS-1045", "In Progress")

    actions = [(event["action"], event["detail"]) for event in events_for("AMS-1045")]
    assert (
        qa_handback.QA_RETURNED_ACTION,
        "#1 to Ravi Kumar — Prospect on two contracts is still refused. "
        "[generated suite: 3/7 passed]",
    ) in actions
    # The same two events every other assignment writes, so `previous_developer`
    # can walk this hand-back on the next round trip.
    assert ("ticket_assigned", "Ravi Kumar") in actions
    assert ("ticket_status_changed", "In Progress") in actions


def test_a_second_return_with_the_same_reason_is_still_recorded():
    """`record_event` dedups on (ticket, actor, action, detail), so the same
    defect reported twice in the same words would vanish — which is exactly the
    history worth keeping. The returns are numbered to prevent it."""
    record_event("AMS-1045", "system", "ticket_assigned", detail="Ravi Kumar")
    record_event("AMS-1045", "human", "ticket_assigned", detail="Priya Nair")

    jira = MagicMock()
    jira.get_issue.return_value = {"key": "AMS-1045", "assignee": "Priya Nair", "status": "QA"}
    jira.assign_issue.side_effect = lambda key, assignee: {"key": key, "assignee": assignee}
    jira.set_issue_status.side_effect = lambda key, status: {"key": key, "status": status}
    client = _client("Priya Nair")

    with patch.object(s3_router, "get_jira_client", return_value=jira):
        first = client.post(
            "/api/s3/jira/return-to-developer",
            json={"key": "AMS-1045", "reason": "Still refused."},
        )
        second = client.post(
            "/api/s3/jira/return-to-developer",
            json={"key": "AMS-1045", "reason": "Still refused."},
        )

    assert first.json()["returns"] == 1
    assert second.json()["returns"] == 2
    returned = [
        event["detail"]
        for event in events_for("AMS-1045")
        if event["action"] == qa_handback.QA_RETURNED_ACTION
    ]
    assert returned == ["#1 to Ravi Kumar — Still refused.", "#2 to Ravi Kumar — Still refused."]


def test_return_refuses_when_the_ticket_has_no_developer_in_its_history():
    """409 and an instruction, rather than inventing a name."""
    record_event("AMS-1045", "human", "ticket_assigned", detail="Priya Nair")

    jira = MagicMock()
    jira.get_issue.return_value = {"key": "AMS-1045", "assignee": "Priya Nair", "status": "QA"}

    with patch.object(s3_router, "get_jira_client", return_value=jira):
        response = _client("Priya Nair").post(
            "/api/s3/jira/return-to-developer", json={"key": "AMS-1045", "reason": "Wrong copy."}
        )

    assert response.status_code == 409
    assert "nobody to hand it back to" in response.json()["detail"]
    jira.assign_issue.assert_not_called()
    jira.set_issue_status.assert_not_called()


def test_return_refuses_a_tester_who_does_not_hold_the_ticket():
    """Same rule as the assign endpoint, and it has to be: otherwise the fail
    path would be a way around it — any tester could bounce anyone's ticket."""
    record_event("AMS-1045", "system", "ticket_assigned", detail="Ravi Kumar")
    record_event("AMS-1045", "human", "ticket_assigned", detail="Priya Nair")

    jira = MagicMock()
    jira.get_issue.return_value = {"key": "AMS-1045", "assignee": "Priya Nair", "status": "QA"}

    with patch.object(s3_router, "get_jira_client", return_value=jira):
        response = _client("Tom Becker").post(
            "/api/s3/jira/return-to-developer", json={"key": "AMS-1045", "reason": "Nope."}
        )

    assert response.status_code == 403
    assert "Priya Nair" in response.json()["detail"]
    jira.assign_issue.assert_not_called()


def test_a_manager_may_hand_back_a_ticket_they_do_not_hold():
    record_event("AMS-1045", "system", "ticket_assigned", detail="Ravi Kumar")
    record_event("AMS-1045", "human", "ticket_assigned", detail="Priya Nair")

    jira = MagicMock()
    jira.get_issue.return_value = {"key": "AMS-1045", "assignee": "Priya Nair", "status": "QA"}
    jira.assign_issue.side_effect = lambda key, assignee: {"key": key, "assignee": assignee}
    jira.set_issue_status.side_effect = lambda key, status: {"key": key, "status": status}

    with patch.object(s3_router, "get_jira_client", return_value=jira):
        response = _client("Manager").post(
            "/api/s3/jira/return-to-developer",
            json={"key": "AMS-1045", "reason": "Reopened after the demo."},
        )

    assert response.status_code == 200
    assert response.json()["developer"] == "Ravi Kumar"


def test_an_unreadable_current_holder_does_not_become_a_silent_grant():
    """If Jira cannot say who holds the ticket, a non-manager is refused —
    never the other way round."""
    record_event("AMS-1045", "system", "ticket_assigned", detail="Ravi Kumar")
    record_event("AMS-1045", "human", "ticket_assigned", detail="Priya Nair")

    jira = MagicMock()
    jira.get_issue.side_effect = JiraError("no recording")
    jira.assign_issue.side_effect = lambda key, assignee: {"key": key, "assignee": assignee}
    jira.set_issue_status.side_effect = lambda key, status: {"key": key, "status": status}

    with patch.object(s3_router, "get_jira_client", return_value=jira):
        response = _client("Priya Nair").post(
            "/api/s3/jira/return-to-developer", json={"key": "AMS-1045", "reason": "Still red."}
        )

    # An unreadable holder reads as unassigned, which anyone may pick up — so
    # this succeeds, and the ticket goes to the last non-tester holder. What it
    # must never do is let Priya take a ticket Jira says belongs to someone else.
    assert response.status_code == 200
    assert response.json()["developer"] == "Ravi Kumar"
