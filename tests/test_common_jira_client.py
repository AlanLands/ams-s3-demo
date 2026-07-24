"""Verifies common/jira_client.py's record/replay contract: a `replay` run
must reproduce a prior `record` run's results with zero network calls, which
is the rehearsal-safety guarantee the S3 Jira beat depends on.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from common import jira_client
from common.jira_client import JiraClient, JiraError


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(jira_client, "_CACHE_ROOT", tmp_path)
    monkeypatch.setenv("JIRA_EMAIL", "demo@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "fake-token-not-real")
    monkeypatch.setenv("JIRA_BASE_URL", "https://example.atlassian.net")


def _fake_response(body: bytes):
    response = MagicMock()
    response.read.return_value = body
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    return response


def test_create_issue_record_then_replay_matches_with_no_network(monkeypatch):
    raw_payload = json.dumps(
        {
            "key": "AMS-42",
            "id": "10042",
            "self": "https://example.atlassian.net/rest/api/3/issue/10042",
            "fields": {
                "summary": "Add coverage-upgrade option",
                "status": {"name": "To Do"},
                "issuetype": {"name": "Task"},
            },
        }
    ).encode("utf-8")

    with patch("common.jira_client.urlopen", return_value=_fake_response(raw_payload)) as mock_open:
        monkeypatch.setenv("JIRA_MODE", "record")
        client = JiraClient()
        recorded = client.create_issue("AMS", "Add coverage-upgrade option", "body text")
        assert mock_open.call_count == 1

    assert recorded == {
        "key": "AMS-42",
        "id": "10042",
        "self": "https://example.atlassian.net/rest/api/3/issue/10042",
        "summary": "Add coverage-upgrade option",
        "status": "To Do",
        "issue_type": "Task",
        "assignee": None,
        "description": "body text",
    }

    with patch("common.jira_client.urlopen") as mock_open_replay:
        monkeypatch.setenv("JIRA_MODE", "replay")
        replayed = JiraClient().create_issue("AMS", "Add coverage-upgrade option", "body text")
        assert mock_open_replay.call_count == 0
        assert replayed == recorded


def test_create_issue_carries_assignee_name_through(monkeypatch):
    # Jira's create-issue response never echoes `fields` back, so the
    # assignee has to be carried through explicitly rather than read off
    # the response — this is what that behavior looks like end to end.
    raw_payload = json.dumps({"key": "AMS-103", "id": "10103", "self": None}).encode("utf-8")

    with patch("common.jira_client.urlopen", return_value=_fake_response(raw_payload)):
        monkeypatch.setenv("JIRA_MODE", "record")
        result = JiraClient().create_issue(
            "AMS", "Add tier to rate table", "reason", assignee_name="Ravi Kumar"
        )

    assert result["assignee"] == "Ravi Kumar"
    assert result["key"] == "AMS-103"

    with patch("common.jira_client.urlopen") as mock_open_replay:
        monkeypatch.setenv("JIRA_MODE", "replay")
        replayed = JiraClient().create_issue(
            "AMS", "Add tier to rate table", "reason", assignee_name="Ravi Kumar"
        )
        assert mock_open_replay.call_count == 0
        assert replayed == result


def test_search_issues_record_then_replay_matches_with_no_network(monkeypatch):
    raw_payload = json.dumps(
        {
            "issues": [
                {
                    "key": "AMS-42",
                    "id": "10042",
                    "fields": {"summary": "x", "status": {"name": "In Progress"}},
                }
            ]
        }
    ).encode("utf-8")

    with patch("common.jira_client.urlopen", return_value=_fake_response(raw_payload)):
        monkeypatch.setenv("JIRA_MODE", "record")
        recorded = JiraClient().search_issues("project = AMS")

    assert recorded[0]["status"] == "In Progress"

    with patch("common.jira_client.urlopen") as mock_open_replay:
        monkeypatch.setenv("JIRA_MODE", "replay")
        replayed = JiraClient().search_issues("project = AMS")
        assert mock_open_replay.call_count == 0
        assert replayed == recorded


def test_replay_without_a_recording_raises_clear_error(monkeypatch):
    # search_issues has no deterministic fallback (a real Jira search result
    # isn't derivable from the query alone) so it still hard-fails without a
    # prior recording — unlike create_issue/assign_issue/set_issue_status,
    # which synthesize instead (see the tests below).
    monkeypatch.setenv("JIRA_MODE", "replay")
    with patch("common.jira_client.urlopen") as mock_open:
        with pytest.raises(JiraError, match="JIRA_MODE=record"):
            JiraClient().search_issues("project = AMS")
        assert mock_open.call_count == 0


def test_create_issue_synthesizes_a_ticket_without_a_recording(monkeypatch):
    # Nothing about "what key would Jira assign" needs faithful replay for
    # this demo — create_issue synthesizes a plausible ticket instead of
    # hard-failing, so any AI-suggested cross-team ticket works out of the
    # box without pre-seeding every possible summary/description combo.
    monkeypatch.setenv("JIRA_MODE", "replay")
    with patch("common.jira_client.urlopen") as mock_open:
        issue = JiraClient().create_issue(
            "AMS", "Add new coverage tier to BillingGateway rate table", assignee_name=None
        )
        assert mock_open.call_count == 0

    assert issue["summary"] == "Add new coverage tier to BillingGateway rate table"
    assert issue["status"] == "To Do"
    assert issue["key"].startswith("AMS-")

    # A later get_issue() for that same synthesized key sees it too.
    fetched = JiraClient().get_issue(issue["key"])
    assert fetched["status"] == "To Do"


def test_assign_and_set_status_work_in_replay_without_a_recording(monkeypatch):
    monkeypatch.setenv("JIRA_MODE", "replay")
    with patch("common.jira_client.urlopen") as mock_open:
        client = JiraClient()
        assigned = client.assign_issue("AMS-201", "Ravi Kumar")
        assert assigned == {"key": "AMS-201", "assignee": "Ravi Kumar"}

        moved = client.set_issue_status("AMS-201", "Done")
        assert moved == {"key": "AMS-201", "status": "Done"}
        assert mock_open.call_count == 0

    # Both changes are visible to a later get_issue() — this is what lets a
    # different login (a different team) see a ticket move to Done.
    fetched = JiraClient().get_issue("AMS-201")
    assert fetched["assignee"] == "Ravi Kumar"
    assert fetched["status"] == "Done"


def test_live_call_without_credentials_fails_before_any_network_attempt(monkeypatch):
    monkeypatch.delenv("JIRA_API_TOKEN", raising=False)
    monkeypatch.setenv("JIRA_MODE", "live")
    with patch("common.jira_client.urlopen") as mock_open:
        with pytest.raises(JiraError, match="JIRA_API_TOKEN"):
            JiraClient().create_issue("AMS", "summary")
        assert mock_open.call_count == 0


def test_unknown_mode_raises(monkeypatch):
    monkeypatch.setenv("JIRA_MODE", "bogus")
    with pytest.raises(JiraError, match="JIRA_MODE"):
        jira_client._jira_mode()


def test_attach_file_caches_per_content_digest(monkeypatch):
    raw_payload = json.dumps([{"id": "9001", "filename": "before.png"}]).encode("utf-8")

    with patch("common.jira_client.urlopen", return_value=_fake_response(raw_payload)) as mock_open:
        monkeypatch.setenv("JIRA_MODE", "record")
        recorded = JiraClient().attach_file("AMS-42", "before.png", b"fake-png-bytes", "image/png")
        assert mock_open.call_count == 1

    assert recorded == {"filename": "before.png", "ok": True, "attachment_ids": ["9001"]}

    with patch("common.jira_client.urlopen") as mock_open_replay:
        monkeypatch.setenv("JIRA_MODE", "replay")
        replayed = JiraClient().attach_file("AMS-42", "before.png", b"fake-png-bytes", "image/png")
        assert mock_open_replay.call_count == 0
        assert replayed == recorded
