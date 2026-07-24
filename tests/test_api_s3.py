"""Verifies the S3 REST endpoints -- thin API wrappers over s3_enhancement's
already-tested Enhancement Delivery modules.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
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


def test_reset_marker_401s_without_login():
    client = TestClient(app)
    assert client.get("/api/s3/reset-marker").status_code == 401


def test_reset_marker_reflects_events_log_marker(tmp_path, monkeypatch):
    monkeypatch.setenv("TICKET_RESET_MARKER_PATH", str(tmp_path / "missing"))
    client = _client()

    assert client.get("/api/s3/reset-marker").json() == {"marker": "0"}

    marker_path = tmp_path / ".s3_reset_marker"
    marker_path.write_text("99", encoding="utf-8")
    monkeypatch.setenv("TICKET_RESET_MARKER_PATH", str(marker_path))

    assert client.get("/api/s3/reset-marker").json() == {"marker": "99"}


def test_analyze_401s_without_login():
    client = TestClient(app)
    response = client.post("/api/s3/analyze", json={"tier_name": "Elite"})
    assert response.status_code == 401


def test_analyze_adhoc_401s_without_login():
    client = TestClient(app)
    response = client.post("/api/s3/analyze-adhoc", json={"cr_text": "Some ticket text"})
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


def test_design_doc_401s_without_login():
    client = TestClient(app)
    response = client.post("/api/s3/design-doc", json={"tier_name": "Elite"})
    assert response.status_code == 401


def test_apply_401s_without_login():
    client = TestClient(app)
    response = client.post("/api/s3/apply", json={"proposal_id": "prop-1"})
    assert response.status_code == 401


def test_add_file_401s_without_login():
    client = TestClient(app)
    response = client.post(
        "/api/s3/add-file",
        json={"proposal_id": "prop-1", "file_path": "a.py", "instruction": "do it"},
    )
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
    assert "token_panel" in body
    assert "naive_input_tokens_estimate" in body["token_panel"]


def test_analyze_reports_scoped_vs_naive_token_comparison():
    """Impact analysis already runs codebase content through the relevance
    funnel (same as code generation) — the response should surface the same
    scoped-vs-naive comparison /s3/generate does, not just a bare answer."""
    client = _client()

    def complete_side_effect(prompt: str, *, usage_out=None, **kwargs):
        if kwargs.get("json_mode") is True:
            return json.dumps(
                {"hours_class": "~40h", "priority_equivalent": "P3", "reasoning": "x"}
            )
        if usage_out is not None:
            usage_out["input_tokens"] = 3502
            usage_out["output_tokens"] = 210
        return "Update policy model, persistence, coverage rules, and portal UI."

    with patch("s3_enhancement.analyze.complete", side_effect=complete_side_effect):
        response = client.post("/api/s3/analyze", json={"tier_name": "Elite"})

    assert response.status_code == 200
    panel = response.json()["token_panel"]
    assert panel["scoped_input_tokens"] == 3502
    assert panel["scoped_output_tokens"] == 210
    # naive_input_tokens_estimate sums relevance.estimate_tokens() over every
    # candidate file in the target — must be a real, positive number (there
    # are real .py files under mockapp/), and comfortably bigger than the
    # scoped figure, since it's the "if we sent everything" baseline.
    assert panel["naive_input_tokens_estimate"] > panel["scoped_input_tokens"]


def test_analyze_adhoc_returns_impact_and_effort_without_file_selection():
    client = _client()

    def complete_side_effect(prompt: str, **kwargs) -> str:
        if kwargs.get("json_mode") is True:
            return json.dumps(
                {
                    "hours_class": "~8h",
                    "priority_equivalent": "P4",
                    "reasoning": "Small, isolated change in another team's app.",
                }
            )
        assert "no source access" in prompt.lower()
        return "Likely a small change to BillingGateway's premium recalculation logic."

    with patch("s3_enhancement.analyze.complete", side_effect=complete_side_effect):
        response = client.post(
            "/api/s3/analyze-adhoc",
            json={
                "cr_text": "BillingGateway needs to handle recalculated premiums.",
                "ticket_number": "AMS-132",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["label"] == AI_SUGGESTION_LABEL
    assert body["impact_analysis"].startswith("Likely a small change")
    assert body["effort_estimate"]["hours_class"] == "~8h"
    assert "file_selection" not in body


def test_analyze_adhoc_empty_text_returns_422():
    client = _client()

    response = client.post("/api/s3/analyze-adhoc", json={"cr_text": "   "})

    assert response.status_code == 422


def test_analyze_adhoc_llm_error_returns_502():
    client = _client()

    with patch("s3_enhancement.analyze.complete", side_effect=LLMError("boom")):
        response = client.post("/api/s3/analyze-adhoc", json={"cr_text": "Some ticket text"})

    assert response.status_code == 502
    assert response.json()["detail"] == "boom"


def test_cross_team_impact_401s_without_login():
    client = TestClient(app)
    response = client.post("/api/s3/impact/cross-team", json={"tier_name": "Elite"})
    assert response.status_code == 401


def test_cross_team_impact_returns_impacts_and_token_panel():
    """Cross-team impact runs the same relevance-funnel codebase context as
    impact analysis — it should get the same scoped-vs-naive visibility."""
    client = _client()

    def complete_side_effect(prompt: str, *, usage_out=None, **kwargs):
        if usage_out is not None:
            usage_out["input_tokens"] = 3410
            usage_out["output_tokens"] = 95
        return json.dumps({"impacts": []})

    with patch("s3_enhancement.analyze.complete", side_effect=complete_side_effect):
        response = client.post("/api/s3/impact/cross-team", json={"tier_name": "Elite"})

    assert response.status_code == 200
    body = response.json()
    assert body["label"] == AI_SUGGESTION_LABEL
    assert body["impacts"] == []
    panel = body["token_panel"]
    assert panel["scoped_input_tokens"] == 3410
    assert panel["naive_input_tokens_estimate"] > panel["scoped_input_tokens"]


def test_cross_team_impact_llm_error_returns_502():
    client = _client()

    with patch("s3_enhancement.analyze.complete", side_effect=LLMError("boom")):
        response = client.post("/api/s3/impact/cross-team", json={"tier_name": "Elite"})

    assert response.status_code == 502
    assert response.json()["detail"] == "boom"


def test_generate_llm_error_returns_502():
    client = _client()

    with patch("s3_enhancement.codegen.stream_complete", side_effect=LLMError("boom")):
        response = client.post("/api/s3/generate", json={"tier_name": "Elite"})

    assert response.status_code == 502
    assert response.json()["detail"] == "boom"


def test_tests_failure_carries_returncode_and_passed_flag():
    client = _client()
    fake_result = SimpleNamespace(
        diff_text="diff --git a/tests/x.py b/tests/x.py",
        files_changed=["tests/x.py"],
        used_replay=True,
        scoped_input_tokens=10,
        scoped_output_tokens=5,
        tokens_estimated=False,
    )

    with (
        patch("api.routers.s3.generate_tests", return_value=fake_result),
        patch("s3_enhancement.testrun.subprocess.run") as run,
    ):
        run.return_value.returncode = 1
        run.return_value.stdout = "1 failed, 4 passed"
        run.return_value.stderr = ""
        response = client.post("/api/s3/tests", json={"tier_name": "Elite"})

    assert response.status_code == 200
    body = response.json()
    assert body["returncode"] == 1
    assert body["passed"] is False
    assert "1 failed" in body["pytest_output"]
    # The mocked runner never wrote JUnit XML — the parsed case list must
    # degrade to empty, not crash the endpoint.
    assert body["cases"] == []


def test_run_tests_missing_runner_returns_502():
    """A Java target's mvn not being on PATH must surface as a clean 502
    detail, not an uncaught FileNotFoundError 500."""
    from fastapi import HTTPException

    from api.routers.s3 import _run_suite_or_502

    target = SimpleNamespace(
        test_command=("definitely-not-a-real-binary-xyz", "test"),
        test_cwd=None,
        testgen_allowlist=[],
    )
    with pytest.raises(HTTPException) as excinfo:
        _run_suite_or_502(target)
    assert excinfo.value.status_code == 502
    assert "not found" in excinfo.value.detail


def test_tests_generate_401s_without_login():
    client = TestClient(app)
    response = client.post("/api/s3/tests/generate", json={"tier_name": "Elite"})
    assert response.status_code == 401


def test_tests_run_401s_without_login():
    client = TestClient(app)
    response = client.post("/api/s3/tests/run", json={"tier_name": "Elite"})
    assert response.status_code == 401


def test_tests_mutation_401s_without_login():
    client = TestClient(app)
    response = client.post("/api/s3/tests/mutation", json={"tier_name": "Elite"})
    assert response.status_code == 401


def test_tests_generate_returns_diff_without_running():
    """Beat 1 of the split flow: the test file is generated and staged, but
    nothing runs — no runner subprocess, no pytest output in the payload."""
    client = _client()
    fake_result = SimpleNamespace(
        diff_text="diff --git a/tests/x.py b/tests/x.py",
        files_changed=["tests/x.py"],
        used_replay=True,
        scoped_input_tokens=10,
        scoped_output_tokens=5,
        tokens_estimated=False,
    )

    with (
        patch("api.routers.s3.generate_tests", return_value=fake_result),
        patch("s3_enhancement.testrun.subprocess.run") as run,
    ):
        response = client.post("/api/s3/tests/generate", json={"tier_name": "Elite"})

    assert response.status_code == 200
    body = response.json()
    assert body["label"] == AI_SUGGESTION_LABEL
    assert body["diff_text"].startswith("diff --git")
    assert body["files_changed"] == ["tests/x.py"]
    assert "pytest_output" not in body
    run.assert_not_called()


def test_tests_run_409s_before_generation():
    client = _client()

    with patch("api.routers.s3.testrun.generated_test_file_exists", return_value=False):
        response = client.post("/api/s3/tests/run", json={"tier_name": "Elite"})

    assert response.status_code == 409
    assert "generate the tests first" in response.json()["detail"]


def test_tests_run_returns_parsed_cases():
    from s3_enhancement.testrun import SuiteRun, TestCase

    client = _client()
    fake_run = SuiteRun(
        output="2 passed",
        returncode=0,
        cases=[
            TestCase(
                name="test_default_tier_is_standard",
                classname="tests.test_s3_coverage_upgrade",
                description="Default tier is standard",
                status="passed",
                time_s=0.01,
                message=None,
            ),
            TestCase(
                name="test_upgrade_recalculates_premium",
                classname="tests.test_s3_coverage_upgrade",
                description="Upgrade recalculates premium",
                status="passed",
                time_s=0.02,
                message=None,
            ),
        ],
        duration_s=0.5,
    )

    with (
        patch("api.routers.s3.testrun.generated_test_file_exists", return_value=True),
        patch("api.routers.s3.testrun.run_suite", return_value=fake_run),
    ):
        response = client.post("/api/s3/tests/run", json={"tier_name": "Elite"})

    assert response.status_code == 200
    body = response.json()
    assert body["passed"] is True
    assert body["summary"] == {"total": 2, "passed": 2, "failed": 0, "errors": 0, "skipped": 0}
    assert [case["description"] for case in body["cases"]] == [
        "Default tier is standard",
        "Upgrade recalculates premium",
    ]


def test_tests_mutation_returns_verdict_and_reverted_flag():
    from s3_enhancement.testrun import MutationRun, SuiteRun, TestCase

    client = _client()
    fake_run = SuiteRun(
        output="1 failed, 1 passed",
        returncode=1,
        cases=[
            TestCase(
                name="test_same_tier_raises",
                classname="tests.test_s3_coverage_upgrade",
                description="Same tier raises",
                status="failed",
                time_s=0.01,
                message="ValueError not raised",
            ),
        ],
        duration_s=0.4,
    )
    fake_mutation = MutationRun(
        description="Weakened the same-tier guard",
        rel_path="mockapp/core/coverage.py",
        mutation_diff="--- a/mockapp/core/coverage.py\n+++ b/mockapp/core/coverage.py\n",
        run=fake_run,
        tests_caught_bug=True,
    )

    with patch("api.routers.s3.testrun.run_mutation", return_value=fake_mutation):
        response = client.post("/api/s3/tests/mutation", json={"tier_name": "Elite"})

    assert response.status_code == 200
    body = response.json()
    assert body["tests_caught_bug"] is True
    assert body["reverted"] is True
    assert body["file"] == "mockapp/core/coverage.py"
    assert body["cases"][0]["status"] == "failed"


def test_tests_mutation_409s_when_unavailable():
    from s3_enhancement.testrun import MutationError

    client = _client()

    with patch(
        "api.routers.s3.testrun.run_mutation",
        side_effect=MutationError("Generate and run the tests first"),
    ):
        response = client.post("/api/s3/tests/mutation", json={"tier_name": "Elite"})

    assert response.status_code == 409
    assert "Generate and run the tests first" in response.json()["detail"]


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


def test_design_doc_returns_label_and_text():
    client = _client()

    with patch("s3_enhancement.docgen.complete", return_value="Design doc text."):
        response = client.post("/api/s3/design-doc", json={"tier_name": "Elite"})

    assert response.status_code == 200
    body = response.json()
    assert body["label"] == AI_SUGGESTION_LABEL
    assert body["design_doc"] == "Design doc text."


def test_design_doc_llm_error_returns_502():
    client = _client()

    with patch("s3_enhancement.docgen.complete", side_effect=LLMError("boom")):
        response = client.post("/api/s3/design-doc", json={"tier_name": "Elite"})

    assert response.status_code == 502
    assert response.json()["detail"] == "boom"


def test_apply_calls_apply_change_with_file_path():
    client = _client()

    with patch("api.routers.s3.apply_change", return_value=["a.py"]) as apply_change:
        response = client.post(
            "/api/s3/apply", json={"proposal_id": "prop-1", "file_path": "a.py"}
        )

    apply_change.assert_called_once_with("prop-1", "a.py")
    assert response.status_code == 200
    assert response.json() == {
        "proposal_id": "prop-1",
        "applied_files": ["a.py"],
        "post_apply": {"ok": True, "steps": []},
    }


def test_apply_mockapp_files_runs_post_apply_migration():
    """Applying files under mockapp/ must rebuild the SQLite schema in a
    subprocess (the applied CR may have added a column the existing DB
    predates) — the crash-after-apply regression."""
    client = _client()

    with (
        patch("api.routers.s3.apply_change", return_value=["mockapp/core/db.py"]),
        patch("api.routers.s3.subprocess.run") as run,
    ):
        run.return_value.returncode = 0
        run.return_value.stdout = ""
        run.return_value.stderr = ""
        response = client.post("/api/s3/apply", json={"proposal_id": "prop-1"})

    assert response.status_code == 200
    assert run.call_count == 1
    argv = run.call_args.args[0]
    assert argv[1:] == ["-m", "mockapp.core.seed"]
    post_apply = response.json()["post_apply"]
    assert post_apply["ok"] is True
    assert post_apply["steps"][0]["returncode"] == 0
    assert post_apply["steps"][0]["output_tail"] == ""


def test_apply_post_apply_failure_carried_in_response(tmp_path, monkeypatch):
    """A migration crash after apply — the applied CR broke the app — must
    reach the caller with its traceback and land on the ticket timeline,
    not vanish into a discarded subprocess result."""
    events_path = tmp_path / "ticket_events.jsonl"
    monkeypatch.setenv("TICKET_EVENTS_PATH", str(events_path))
    client = _client()

    with (
        patch("api.routers.s3.apply_change", return_value=["mockapp/core/db.py"]),
        patch("api.routers.s3.subprocess.run") as run,
    ):
        run.return_value.returncode = 1
        run.return_value.stdout = "Traceback (most recent call last):\nKeyError: 'deductible'"
        run.return_value.stderr = ""
        response = client.post(
            "/api/s3/apply", json={"proposal_id": "prop-1", "ticket_number": "AMS-101"}
        )

    assert response.status_code == 200
    post_apply = response.json()["post_apply"]
    assert post_apply["ok"] is False
    step = post_apply["steps"][0]
    assert step["returncode"] == 1
    assert "Traceback" in step["output_tail"]

    events = [json.loads(line) for line in events_path.read_text().splitlines()]
    failed = [e for e in events if e["action"] == "post_apply_migration_failed"]
    assert len(failed) == 1
    assert failed[0]["actor"] == "system"
    assert "KeyError: 'deductible'" in failed[0]["detail"]


def test_apply_non_stateful_files_skips_post_apply_migration():
    client = _client()

    with (
        patch("api.routers.s3.apply_change", return_value=["a.py"]),
        patch("api.routers.s3.subprocess.run") as run,
    ):
        response = client.post("/api/s3/apply", json={"proposal_id": "prop-1"})

    assert response.status_code == 200
    run.assert_not_called()


def test_apply_llm_error_returns_502():
    client = _client()

    with patch("api.routers.s3.apply_change", side_effect=LLMError("no such proposal")):
        response = client.post("/api/s3/apply", json={"proposal_id": "prop-1"})

    assert response.status_code == 502
    assert response.json()["detail"] == "no such proposal"


def test_add_file_returns_diff_and_files_changed():
    client = _client()
    fake_result = SimpleNamespace(
        proposal_id="prop-1",
        diff_text="diff --git a/a.py b/a.py",
        files_changed=["a.py"],
        message=None,
        scoped_input_tokens=10,
        scoped_output_tokens=5,
    )

    with patch("api.routers.s3.add_file_to_proposal", return_value=fake_result) as add_file:
        response = client.post(
            "/api/s3/add-file",
            json={"proposal_id": "prop-1", "file_path": "a.py", "instruction": "add a field"},
        )

    add_file.assert_called_once_with("prop-1", "a.py", "add a field")
    assert response.status_code == 200
    body = response.json()
    assert body["label"] == AI_SUGGESTION_LABEL
    assert body["files_changed"] == ["a.py"]
    assert body["token_panel"] == {"scoped_input_tokens": 10, "scoped_output_tokens": 5}


def test_add_file_llm_error_returns_502():
    client = _client()

    with patch("api.routers.s3.add_file_to_proposal", side_effect=LLMError("nope")):
        response = client.post(
            "/api/s3/add-file",
            json={"proposal_id": "prop-1", "file_path": "a.py", "instruction": "add a field"},
        )

    assert response.status_code == 502
    assert response.json()["detail"] == "nope"


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
