"""Verifies the API auth gate: login/logout round-trip, and that every
other router 401s without a valid session — the server-side guarantee that
replaces Streamlit's `render_login_gate()` + `st.stop()`.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.main import app
from s1_triage.roster_auth import PASSCODE_BY_NAME


def _client() -> TestClient:
    return TestClient(app)


def test_login_with_correct_passcode_sets_session_and_returns_identity():
    client = _client()
    response = client.post(
        "/api/auth/login",
        json={"name": "Jordan Blake", "passcode": PASSCODE_BY_NAME["Jordan Blake"]},
    )
    assert response.status_code == 200
    assert response.json() == {"name": "Jordan Blake", "role": "engineer", "group": "Batch Ops"}
    assert "ams_session" in response.cookies


def test_login_with_wrong_passcode_is_rejected():
    client = _client()
    response = client.post("/api/auth/login", json={"name": "Jordan Blake", "passcode": "0000"})
    assert response.status_code == 401


def test_manager_login_has_no_group():
    client = _client()
    response = client.post(
        "/api/auth/login", json={"name": "Manager", "passcode": PASSCODE_BY_NAME["Manager"]}
    )
    assert response.status_code == 200
    assert response.json() == {"name": "Manager", "role": "manager", "group": None}


def test_me_without_session_is_401():
    client = _client()
    response = client.get("/api/auth/me")
    assert response.status_code == 401


def test_me_after_login_returns_identity_then_logout_clears_it():
    client = _client()
    client.post(
        "/api/auth/login", json={"name": "Ravi Kumar", "passcode": PASSCODE_BY_NAME["Ravi Kumar"]}
    )
    assert client.get("/api/auth/me").status_code == 200

    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401


def test_s3_cr_401s_without_login():
    client = _client()
    response = client.get("/api/s3/cr")
    assert response.status_code == 401
