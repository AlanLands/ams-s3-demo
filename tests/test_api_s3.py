"""Verifies the S3 REST endpoints -- thin API wrappers over s3_enhancement's
already-tested Enhancement Delivery modules.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from api.main import app
from common.constants import AI_SUGGESTION_LABEL
from common.gitlab_client import GitLabError
from common.llm import LLMError
from s1_triage.roster_auth import PASSCODE_BY_NAME


def _login(client: TestClient, name: str) -> None:
    response = client.post(
        "/api/auth/login", json={"name": name, "passcode": PASSCODE_BY_NAME[name]}
    )
    assert response.status_code == 200


def _client() -> TestClient:
    client = TestClient(app)
    _login(client, "Ravi Kumar")
    return client


def test_cr_401s_without_login():
    client = TestClient(app)
    assert client.get("/api/s3/cr").status_code == 401


def test_analyze_401s_without_login():
    client = TestClient(app)
    response = client.post("/api/s3/analyze", json={"tier_name": "Elite"})
    assert response.status_code == 401


def test_generate_401s_without_login():
    client = TestClient(app)
    response = client.post("/api/s3/generate", json={"tier_name": "Elite"})
    assert response.status_code == 401


def test_tests_401s_without_login():
    client = TestClient(app)
    response = client.post("/api/s3/tests", json={"tier_name": "Elite"})
    assert response.status_code == 401


def test_release_notes_401s_without_login():
    client = TestClient(app)
    response = client.post("/api/s3/release-notes", json={"tier_name": "Elite"})
    assert response.status_code == 401


def test_harness_latest_401s_without_login():
    client = TestClient(app)
    assert client.get("/api/s3/harness/latest").status_code == 401


def test_gitlab_projects_401s_without_login():
    client = TestClient(app)
    assert client.get("/api/s3/gitlab/projects").status_code == 401


def test_gitlab_scope_401s_without_login():
    client = TestClient(app)
    response = client.post("/api/s3/gitlab/projects/1/scope", json={"tier_name": "Elite"})
    assert response.status_code == 401


def test_gitlab_scope_auto_401s_without_login():
    client = TestClient(app)
    response = client.post("/api/s3/gitlab/scope-auto", json={"tier_name": "Elite"})
    assert response.status_code == 401


def test_cr_valid_tier_returns_rendered_change_request():
    client = _client()

    response = client.get("/api/s3/cr", params={"tier_name": "Elite"})

    assert response.status_code == 200
    body = response.json()
    assert body["tier_name"] == "Elite"
    assert "Elite" in body["cr_text"]


def test_cr_invalid_tier_returns_422():
    client = _client()

    response = client.get("/api/s3/cr", params={"tier_name": "client/tier"})

    assert response.status_code == 422


def test_analyze_returns_impact_effort_and_file_selection():
    client = _client()

    def complete_side_effect(prompt: str, **kwargs) -> str:
        if kwargs.get("json_mode") is True:
            return json.dumps(
                {
                    "hours_class": "~40h",
                    "priority_equivalent": "P3",
                    "reasoning": "Small scoped change across policy and UI files.",
                }
            )
        assert "impact analysis" in prompt.lower()
        return "Update policy model, persistence, coverage rules, and portal UI."

    with patch("s3_enhancement.analyze.complete", side_effect=complete_side_effect):
        response = client.post("/api/s3/analyze", json={"tier_name": "Elite"})

    assert response.status_code == 200
    body = response.json()
    assert body["label"] == AI_SUGGESTION_LABEL
    assert body["impact_analysis"].startswith("Update policy model")
    assert body["effort_estimate"]["hours_class"] == "~40h"
    assert body["file_selection"]["selected_files"]


def test_generate_llm_error_returns_502():
    client = _client()

    with patch("s3_enhancement.codegen.stream_complete", side_effect=LLMError("boom")):
        response = client.post("/api/s3/generate", json={"tier_name": "Elite"})

    assert response.status_code == 502
    assert response.json()["detail"] == "boom"


def test_tests_llm_error_returns_502():
    client = _client()

    with patch("s3_enhancement.testgen.stream_complete", side_effect=LLMError("boom")):
        response = client.post("/api/s3/tests", json={"tier_name": "Elite"})

    assert response.status_code == 502
    assert response.json()["detail"] == "boom"


def test_release_notes_returns_label_and_text():
    client = _client()

    with patch("s3_enhancement.docgen.complete", return_value="Release note text."):
        response = client.post("/api/s3/release-notes", json={"tier_name": "Elite"})

    assert response.status_code == 200
    body = response.json()
    assert body["label"] == AI_SUGGESTION_LABEL
    assert body["release_notes"] == "Release note text."


def test_harness_latest_without_run_returns_404():
    client = _client()

    with patch("api.routers.s3.latest_harness_run", return_value=None):
        response = client.get("/api/s3/harness/latest")

    assert response.status_code == 404


def test_gitlab_projects_returns_project_list():
    client = _client()
    gitlab = MagicMock()
    gitlab.list_projects.return_value = [{"id": 1, "name": "demo-repo"}]

    with patch("api.routers.s3.get_client", return_value=gitlab):
        response = client.get("/api/s3/gitlab/projects")

    assert response.status_code == 200
    assert response.json() == [{"id": 1, "name": "demo-repo"}]


def test_gitlab_projects_error_returns_502():
    client = _client()
    gitlab = MagicMock()
    gitlab.list_projects.side_effect = GitLabError("no token")

    with patch("api.routers.s3.get_client", return_value=gitlab):
        response = client.get("/api/s3/gitlab/projects")

    assert response.status_code == 502
    assert response.json()["detail"] == "no token"


def test_gitlab_scope_returns_repo_size_and_selected_files():
    client = _client()
    gitlab = MagicMock()
    gitlab.list_repo_paths.return_value = ["a.py", "b.py"]
    selection = SimpleNamespace(selected={"a.py": "print(1)"})

    with patch("api.routers.s3.get_client", return_value=gitlab), patch(
        "api.routers.s3.discover_gitlab_files", return_value={"a.py": "print(1)"}
    ), patch(
        "api.routers.s3.select_relevant_files", return_value=selection
    ):
        response = client.post("/api/s3/gitlab/projects/1/scope", json={"tier_name": "Elite"})

    assert response.status_code == 200
    body = response.json()
    assert body["repo_size"] == 2
    assert body["files_reached_llm"] == 1


def test_gitlab_scope_auto_picks_repo_and_scopes_it():
    client = _client()
    gitlab = MagicMock()
    gitlab.list_projects.return_value = [
        {"id": 1, "name": "policy-service", "description": "coverage APIs"},
        {"id": 2, "name": "billing-batch", "description": "nightly billing jobs"},
    ]
    gitlab.list_repo_paths.return_value = ["a.py", "b.py"]
    selection = SimpleNamespace(selected={"a.py": "print(1)"})
    suggestion = SimpleNamespace(
        best_match=SimpleNamespace(project_id="1", confidence="high", reasoning="matches coverage"),
        alternates=(),
    )

    with patch("api.routers.s3.get_client", return_value=gitlab), patch(
        "api.routers.s3.suggest_target_repo", return_value=suggestion
    ), patch("api.routers.s3.discover_gitlab_files", return_value={"a.py": "print(1)"}), patch(
        "api.routers.s3.select_relevant_files", return_value=selection
    ):
        response = client.post("/api/s3/gitlab/scope-auto", json={"tier_name": "Elite"})

    assert response.status_code == 200
    body = response.json()
    assert body["label"] == AI_SUGGESTION_LABEL
    assert body["suggested_project"]["id"] == "1"
    assert body["suggested_project"]["name"] == "policy-service"
    assert body["repo_size"] == 2
    assert body["files_reached_llm"] == 1


def test_gitlab_scope_auto_returns_502_on_llm_error():
    client = _client()
    gitlab = MagicMock()
    gitlab.list_projects.return_value = [{"id": 1, "name": "policy-service"}]

    with patch("api.routers.s3.get_client", return_value=gitlab), patch(
        "api.routers.s3.suggest_target_repo", side_effect=LLMError("no candidates")
    ):
        response = client.post("/api/s3/gitlab/scope-auto", json={"tier_name": "Elite"})

    assert response.status_code == 502
