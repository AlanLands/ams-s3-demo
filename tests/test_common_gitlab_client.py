"""Verifies common/gitlab_client.py's record/replay contract: a `replay` run
must reproduce a prior `record` run's results with zero network calls, which
is the rehearsal-safety guarantee the S3 GitLab beat depends on.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from common import gitlab_client
from common.gitlab_client import GitLabClient, GitLabError


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(gitlab_client, "_CACHE_ROOT", tmp_path)
    monkeypatch.setenv("GITLAB_TOKEN", "fake-token-not-real")
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example")


def _fake_response(body: bytes, headers: dict[str, str] | None = None):
    response = MagicMock()
    response.read.return_value = body
    response.headers = headers or {}
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    return response


def test_list_projects_record_then_replay_matches_with_no_network(monkeypatch):
    raw_payload = json.dumps(
        [
            {
                "id": 1,
                "name": "policy-service",
                "name_with_namespace": "alan / policy-service",
                "last_activity_at": "2026-07-01T00:00:00Z",
                "web_url": "https://gitlab.example/alan/policy-service",
                "default_branch": "main",
                "irrelevant_field": "should be dropped",
            }
        ]
    ).encode("utf-8")

    fake_response = _fake_response(raw_payload)
    with patch("common.gitlab_client.urlopen", return_value=fake_response) as mock_open:
        monkeypatch.setenv("GITLAB_MODE", "record")
        client = GitLabClient()
        recorded = client.list_projects()
        assert mock_open.call_count == 1
        assert recorded == [
            {
                "id": 1,
                "name": "policy-service",
                "name_with_namespace": "alan / policy-service",
                "last_activity_at": "2026-07-01T00:00:00Z",
                "web_url": "https://gitlab.example/alan/policy-service",
                "default_branch": "main",
            }
        ]

    with patch("common.gitlab_client.urlopen") as mock_open_replay:
        monkeypatch.setenv("GITLAB_MODE", "replay")
        replayed = GitLabClient().list_projects()
        assert mock_open_replay.call_count == 0
        assert replayed == recorded


def test_fetch_files_caches_per_file_independently(monkeypatch):
    responses = {
        "a.py": _fake_response(b"print('a')"),
        "b.py": _fake_response(b"print('b')"),
    }

    def fake_urlopen(request, timeout):
        for path, response in responses.items():
            if path in request.full_url:
                return response
        raise AssertionError(f"unexpected request: {request.full_url}")

    with patch("common.gitlab_client.urlopen", side_effect=fake_urlopen):
        monkeypatch.setenv("GITLAB_MODE", "record")
        client = GitLabClient()
        fetched = client.fetch_files(1, ["a.py", "b.py"], ref="main")
    assert fetched == {"a.py": "print('a')", "b.py": "print('b')"}

    # Replay a SUBSET of the originally recorded paths -- per-file caching
    # means this must not require the other file to have been requested too.
    with patch("common.gitlab_client.urlopen") as mock_open_replay:
        monkeypatch.setenv("GITLAB_MODE", "replay")
        replayed = GitLabClient().fetch_files(1, ["a.py"], ref="main")
        assert mock_open_replay.call_count == 0
        assert replayed == {"a.py": "print('a')"}


def test_replay_without_a_recording_raises_clear_error(monkeypatch):
    monkeypatch.setenv("GITLAB_MODE", "replay")
    with patch("common.gitlab_client.urlopen") as mock_open:
        with pytest.raises(GitLabError, match="GITLAB_MODE=record"):
            GitLabClient().list_projects()
        assert mock_open.call_count == 0


def test_live_call_without_token_fails_before_any_network_attempt(monkeypatch):
    monkeypatch.delenv("GITLAB_TOKEN", raising=False)
    monkeypatch.setenv("GITLAB_MODE", "live")
    with patch("common.gitlab_client.urlopen") as mock_open:
        with pytest.raises(GitLabError, match="GITLAB_TOKEN"):
            GitLabClient().list_projects()
        assert mock_open.call_count == 0


def test_unknown_mode_raises(monkeypatch):
    monkeypatch.setenv("GITLAB_MODE", "bogus")
    with pytest.raises(GitLabError, match="GITLAB_MODE"):
        gitlab_client._gitlab_mode()
