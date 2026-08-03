"""Verifies application-context routing: ServiceNow CI -> application, team,
Jira project and candidate targets, plus the boundary between "routable" and
"automatable".
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from apps.console.api.main import app
from common.roster import PASSCODE_BY_NAME
from s3_enhancement import applications, routing, targets


def _client() -> TestClient:
    client = TestClient(app)
    response = client.post(
        "/api/auth/login",
        json={"name": "Ravi Kumar", "passcode": PASSCODE_BY_NAME["Ravi Kumar"]},
    )
    assert response.status_code == 200
    return client


# --- the registry -------------------------------------------------------


@pytest.mark.parametrize(
    "ci",
    ["ClaimsPortal", "Claims Portal", "claims portal", "claims-portal", "CLAIMSPORTAL"],
)
def test_ci_spellings_all_resolve_to_one_application(ci):
    """Real CMDBs are inconsistent about case and spacing; none of that
    variation should push a ticket onto the LLM fallback tier."""
    assert applications.route_by_ci(ci) is applications.CLAIMS_PORTAL


def test_unknown_and_absent_ci_are_both_unroutable():
    assert applications.route_by_ci("NoSuchApp") is None
    assert applications.route_by_ci(None) is None
    assert applications.route_by_ci("   ") is None


def test_business_service_resolves_when_unambiguous():
    assert applications.route_by_business_service("Claims Management") is (
        applications.CLAIMS_PORTAL
    )
    assert applications.route_by_business_service("Not A Service") is None
    assert applications.route_by_business_service(None) is None


def test_business_service_declines_to_guess_when_ambiguous(monkeypatch):
    """A business service spanning two applications must return None rather
    than silently picking the first — the coarse field is a fallback, not a
    tiebreaker."""
    shared = "Shared Service"
    twins = {
        app.app_id: applications.Application(
            app_id=app.app_id,
            display_name=app.display_name,
            business_service=shared,
            ci_names=app.ci_names,
            jira_project_key=app.jira_project_key,
            component_team=app.component_team,
            tech_stack=app.tech_stack,
            repo_path=app.repo_path,
        )
        for app in (applications.POLICY_CORE, applications.CLAIMS_PORTAL)
    }
    monkeypatch.setattr(applications, "_REGISTRY", twins)
    assert applications.route_by_business_service(shared) is None


def test_component_team_must_be_a_real_assignment_group():
    with pytest.raises(ValueError, match="not a known assignment group"):
        applications.register_application(
            applications.Application(
                app_id="bogus",
                display_name="Bogus",
                business_service="Bogus Service",
                ci_names=("BogusCI",),
                jira_project_key="AMS",
                component_team="Team That Does Not Exist",
                tech_stack="COBOL",
            )
        )


def test_duplicate_ci_name_is_rejected():
    with pytest.raises(ValueError, match="already routed"):
        applications.register_application(
            applications.Application(
                app_id="impostor",
                display_name="Impostor",
                business_service="Impostor Service",
                ci_names=("Claims Portal",),
                jira_project_key="AMS",
                component_team="Batch Ops",
                tech_stack="Go",
            )
        )


# --- the decision -------------------------------------------------------


def test_ci_route_carries_team_project_and_targets():
    decision = routing.route_ticket(ci="Claims Portal")
    assert decision.method == "ci"
    assert decision.routed
    assert not decision.needs_ai_fallback
    assert decision.application.jira_project_key == "AMS"
    assert decision.component_team == "App Support — ClaimsPortal"
    assert decision.suggested_assignee == "Priya Nair"
    assert decision.candidate_target_ids == (targets.CLAIMSPORTAL_TARGET_ID,)
    assert decision.automation_available


def test_one_ci_can_offer_several_candidate_changes():
    """A CI identifies an application, not a change — mockapp hosts two CRs."""
    decision = routing.route_ticket(ci="PolicyCore")
    assert set(decision.candidate_target_ids) == {
        targets.DEFAULT_TARGET_ID,
        targets.AMENDMENT_TARGET_ID,
    }


def test_routable_but_not_automatable_application():
    """BillingGateway has an owning team and no repo in this console: routing
    succeeds, automation stays off."""
    decision = routing.route_ticket(ci="Billing Gateway")
    assert decision.routed
    assert decision.method == "ci"
    assert decision.component_team == "App Support — BillingGateway"
    assert decision.candidate_target_ids == ()
    assert not decision.automation_available


def test_unrouted_decision_asks_for_the_ai_fallback():
    decision = routing.route_ticket(ci=None, business_service=None)
    assert decision.method == "unrouted"
    assert not decision.routed
    assert decision.needs_ai_fallback
    assert not decision.automation_available
    assert decision.suggested_assignee == ""


def test_ci_wins_over_business_service():
    decision = routing.route_ticket(
        ci="ClaimsPortal", business_service="Policy Administration"
    )
    assert decision.application is applications.CLAIMS_PORTAL
    assert decision.method == "ci"


def test_business_service_used_only_when_ci_absent():
    decision = routing.route_ticket(business_service="Claims Management")
    assert decision.method == "business_service"
    assert decision.application is applications.CLAIMS_PORTAL


# --- the endpoints ------------------------------------------------------


def test_route_endpoint_401s_without_login():
    assert TestClient(app).post("/api/s3/route", json={"ci": "PolicyCore"}).status_code == 401


def test_route_endpoint_returns_the_decision():
    body = _client().post("/api/s3/route", json={"ci": "Claims Portal"}).json()
    assert body["method"] == "ci"
    assert body["routed"] is True
    assert body["matched_on"] == "Claims Portal"
    assert body["automation_available"] is True
    assert body["application"]["component_team"] == "App Support — ClaimsPortal"
    assert body["suggested_assignee"] == "Priya Nair"
    assert body["candidate_targets"][0]["target_id"] == targets.CLAIMSPORTAL_TARGET_ID


def test_route_endpoint_answers_unroutable_rather_than_erroring():
    """A ticket with no CI is the case the LLM fallback exists for, not a
    client error."""
    response = _client().post("/api/s3/route", json={})
    assert response.status_code == 200
    body = response.json()
    assert body["method"] == "unrouted"
    assert body["needs_ai_fallback"] is True
    assert body["application"] is None


def test_problem_record_ci_survives_the_round_trip_to_the_board(tmp_path, monkeypatch):
    """A CI supplied at intake has to come back out of the ticket-events log,
    since that log is where the board reads application context from — and the
    detail field it round-trips through now carries three values, not one."""
    monkeypatch.setenv("TICKET_EVENTS_PATH", str(tmp_path / "ticket_events.jsonl"))
    client = _client()

    created = client.post(
        "/api/s3/jira/problem-record-ticket",
        json={
            "summary": "Claim payout ignores the deductible",
            "problem_id": "PRB0012345",
            "ci": "Claims Portal",
            "business_service": "Claims Management",
        },
    )
    assert created.status_code == 200
    body = created.json()
    new_key = body["issue"]["key"]

    assert body["routing"]["method"] == "ci"
    assert body["routing"]["application"]["display_name"] == "ClaimsPortal"
    assert body["issue"]["problem_id"] == "PRB0012345"
    assert body["issue"]["ci"] == "Claims Portal"
    assert body["issue"]["business_service"] == "Claims Management"

    issues = {i["key"]: i for i in client.get("/api/s3/jira/board").json()["issues"]}
    assert issues[new_key]["ci"] == "Claims Portal"
    assert issues[new_key]["problem_id"] == "PRB0012345"

    events = client.get(f"/api/s3/ticket-events?ticket_number={new_key}").json()
    assert any(e["action"] == "ticket_routed" for e in events["events"])


def test_problem_record_without_ci_still_creates_a_valid_ticket(tmp_path, monkeypatch):
    """Application context is optional at intake — an absent CI routes to the
    AI fallback, it does not fail the ticket."""
    monkeypatch.setenv("TICKET_EVENTS_PATH", str(tmp_path / "ticket_events.jsonl"))
    client = _client()

    created = client.post(
        "/api/s3/jira/problem-record-ticket",
        json={"summary": "Something vague", "problem_id": "PRB0099999"},
    )
    assert created.status_code == 200
    body = created.json()
    assert body["routing"]["needs_ai_fallback"] is True
    assert body["issue"]["problem_id"] == "PRB0099999"
    assert body["issue"]["ci"] == ""


def _adhoc_complete(prompt: str, **_kwargs) -> str:
    """Minimal analyze-adhoc stub: pass both clarification gates, then answer."""
    import json

    if "needs_clarification" in prompt:
        return json.dumps({"needs_clarification": False})
    if "hours_class" in prompt:
        return json.dumps(
            {"hours_class": "~8h", "priority_equivalent": "P4", "reasoning": "Small."}
        )
    return json.dumps({"impact_analysis": "Deductible handling.", "assumptions": []})


def test_ci_route_skips_the_llm_repo_match_entirely(tmp_path, monkeypatch):
    """The deterministic tier's whole point is not paying for the guess. If the
    CI resolved, the GitLab project list must never be fetched."""
    monkeypatch.setenv("TICKET_EVENTS_PATH", str(tmp_path / "ticket_events.jsonl"))
    client = _client()

    with patch("s3_enhancement.analyze.complete", side_effect=_adhoc_complete), patch(
        "apps.console.api.routers.s3.get_client"
    ) as gitlab, patch("apps.console.api.routers.s3.suggest_target_repo") as suggest:
        response = client.post(
            "/api/s3/analyze-adhoc",
            json={
                "cr_text": "Claim payout ignores the deductible.",
                "ticket_number": "AMS-140",
                "ci": "ClaimsPortal",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["routing"]["method"] == "ci"
    assert body["routing"]["application"]["display_name"] == "ClaimsPortal"
    gitlab.assert_not_called()
    suggest.assert_not_called()


def test_missing_ci_still_reaches_the_llm_repo_match(tmp_path, monkeypatch):
    """The converse: with no CI the fallback tier must still run, or removing
    the guess would have quietly removed the capability."""
    monkeypatch.setenv("TICKET_EVENTS_PATH", str(tmp_path / "ticket_events.jsonl"))
    client = _client()

    with patch("s3_enhancement.analyze.complete", side_effect=_adhoc_complete), patch(
        "apps.console.api.routers.s3.get_client"
    ) as gitlab:
        gitlab.return_value.list_projects.return_value = [
            {"id": "7", "name": "claims-service", "description": "Claims"}
        ]
        with patch("apps.console.api.routers.s3.suggest_target_repo") as suggest:
            suggest.return_value = None
            response = client.post(
                "/api/s3/analyze-adhoc",
                json={"cr_text": "Something about claims.", "ticket_number": "AMS-141"},
            )

    assert response.status_code == 200
    assert response.json()["routing"]["method"] == "unrouted"
    suggest.assert_called_once()


def test_applications_endpoint_flags_which_are_automatable():
    body = _client().get("/api/s3/applications").json()
    by_name = {a["display_name"]: a for a in body["applications"]}
    assert by_name["ClaimsPortal"]["automation_available"] is True
    assert by_name["PolicyCore"]["automation_available"] is True
    assert by_name["BillingGateway"]["automation_available"] is False
    assert by_name["DocumentHub"]["automation_available"] is False
