"""Per-file rejection and revert: the two halves of granular acceptance that
per-file Apply on its own doesn't cover — turning a change *down* as a recorded
decision, and undoing one already written to the working tree.

Filesystem-only, like tests/test_s3_codegen.py: a throwaway REPO_ROOT/OUT_ROOT,
no LLM call.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.console.api.main import app
from common.roster import PASSCODE_BY_NAME
from s3_enhancement import codegen
from s3_enhancement.codegen import LLMError


@pytest.fixture
def staged_proposal(tmp_path, monkeypatch):
    """A proposal touching one pre-existing file and one the change creates —
    the two cases revert has to treat differently."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    out_root = repo_root / "s3_enhancement" / "out"
    monkeypatch.setattr(codegen, "REPO_ROOT", repo_root)
    monkeypatch.setattr(codegen, "OUT_ROOT", out_root)

    (repo_root / "existing.py").write_text("ORIGINAL = 1\n")

    staged_dir = out_root / "prop-1" / "staged"
    staged_dir.mkdir(parents=True)
    (staged_dir / "existing.py").write_text("CHANGED = 1\n")
    (staged_dir / "created.py").write_text("NEW = 2\n")
    return repo_root, staged_dir


# --- rejection ----------------------------------------------------------


def test_rejected_file_is_excluded_from_apply_all(staged_proposal):
    repo_root, _ = staged_proposal
    codegen.reject_file("prop-1", "created.py", "Out of scope for this CR")

    applied = codegen.apply_change("prop-1")

    assert applied == ["existing.py"]
    assert not (repo_root / "created.py").exists()
    assert (repo_root / "existing.py").read_text() == "CHANGED = 1\n"


def test_applying_a_rejected_file_by_name_is_refused(staged_proposal):
    """Naming a rejected file explicitly must error rather than override —
    otherwise "apply this one" silently defeats the rejection."""
    codegen.reject_file("prop-1", "created.py", "Out of scope")
    with pytest.raises(LLMError, match="was rejected"):
        codegen.apply_change("prop-1", file_path="created.py")


def test_rejection_reason_is_kept(staged_proposal):
    codegen.reject_file("prop-1", "created.py", "  Out of scope for this CR  ")
    assert codegen.rejected_files("prop-1") == {"created.py": "Out of scope for this CR"}


def test_rejection_can_be_cleared(staged_proposal):
    repo_root, _ = staged_proposal
    codegen.reject_file("prop-1", "created.py", "Changed my mind later")
    codegen.clear_rejection("prop-1", "created.py")

    assert codegen.rejected_files("prop-1") == {}
    assert codegen.apply_change("prop-1") == ["created.py", "existing.py"]
    assert (repo_root / "created.py").exists()


def test_rejecting_an_unknown_file_raises(staged_proposal):
    with pytest.raises(LLMError, match="not part of staged proposal"):
        codegen.reject_file("prop-1", "nope.py", "")


def test_clearing_a_rejection_that_was_never_made_is_a_no_op(staged_proposal):
    assert codegen.clear_rejection("prop-1", "created.py") == {}


# --- revert -------------------------------------------------------------


def test_revert_restores_a_modified_file(staged_proposal):
    repo_root, _ = staged_proposal
    codegen.apply_change("prop-1", file_path="existing.py")
    assert (repo_root / "existing.py").read_text() == "CHANGED = 1\n"

    reverted = codegen.revert_change("prop-1", file_path="existing.py")

    assert reverted == ["existing.py"]
    assert (repo_root / "existing.py").read_text() == "ORIGINAL = 1\n"


def test_revert_deletes_a_file_the_change_created(staged_proposal):
    """The correct inverse of creating a file is removing it — restoring it
    empty would leave a file the repo never had."""
    repo_root, _ = staged_proposal
    codegen.apply_change("prop-1", file_path="created.py")
    assert (repo_root / "created.py").exists()

    codegen.revert_change("prop-1", file_path="created.py")

    assert not (repo_root / "created.py").exists()


def test_revert_all_undoes_the_whole_proposal(staged_proposal):
    repo_root, _ = staged_proposal
    codegen.apply_change("prop-1")

    reverted = codegen.revert_change("prop-1")

    assert reverted == ["created.py", "existing.py"]
    assert (repo_root / "existing.py").read_text() == "ORIGINAL = 1\n"
    assert not (repo_root / "created.py").exists()


def test_revert_after_apply_revise_apply_goes_back_to_the_true_baseline(staged_proposal):
    """First apply wins for the backup. A second apply of newer staged content
    must not overwrite the snapshot, or revert would only undo the last step
    and leave the first one silently applied."""
    repo_root, staged_dir = staged_proposal
    codegen.apply_change("prop-1", file_path="existing.py")
    (staged_dir / "existing.py").write_text("REVISED = 99\n")
    codegen.apply_change("prop-1", file_path="existing.py")
    assert (repo_root / "existing.py").read_text() == "REVISED = 99\n"

    codegen.revert_change("prop-1", file_path="existing.py")

    assert (repo_root / "existing.py").read_text() == "ORIGINAL = 1\n"


def test_revert_is_idempotent(staged_proposal):
    repo_root, _ = staged_proposal
    codegen.apply_change("prop-1")
    codegen.revert_change("prop-1")
    codegen.revert_change("prop-1")
    assert (repo_root / "existing.py").read_text() == "ORIGINAL = 1\n"
    assert not (repo_root / "created.py").exists()


def test_reapply_after_revert_still_works(staged_proposal):
    """A mis-clicked Revert must be recoverable without a full demo reset."""
    repo_root, _ = staged_proposal
    codegen.apply_change("prop-1")
    codegen.revert_change("prop-1")
    codegen.apply_change("prop-1")
    assert (repo_root / "existing.py").read_text() == "CHANGED = 1\n"
    assert (repo_root / "created.py").read_text() == "NEW = 2\n"


def test_revert_before_any_apply_raises(staged_proposal):
    with pytest.raises(LLMError, match="has not been applied"):
        codegen.revert_change("prop-1")


def test_revert_of_a_never_applied_file_raises(staged_proposal):
    codegen.apply_change("prop-1", file_path="existing.py")
    with pytest.raises(LLMError, match="has not been applied"):
        codegen.revert_change("prop-1", file_path="created.py")


def test_revertable_files_tracks_what_was_applied(staged_proposal):
    assert codegen.revertable_files("prop-1") == []
    codegen.apply_change("prop-1", file_path="existing.py")
    assert codegen.revertable_files("prop-1") == ["existing.py"]
    codegen.apply_change("prop-1", file_path="created.py")
    assert codegen.revertable_files("prop-1") == ["created.py", "existing.py"]


# --- endpoints ----------------------------------------------------------


def _client() -> TestClient:
    client = TestClient(app)
    response = client.post(
        "/api/auth/login",
        json={"name": "Ravi Kumar", "passcode": PASSCODE_BY_NAME["Ravi Kumar"]},
    )
    assert response.status_code == 200
    return client


def test_reject_and_revert_401_without_login():
    client = TestClient(app)
    assert (
        client.post("/api/s3/reject", json={"proposal_id": "p", "file_path": "a.py"}).status_code
        == 401
    )
    assert client.post("/api/s3/revert", json={"proposal_id": "p"}).status_code == 401


def test_reject_endpoint_records_the_decision_and_reason(staged_proposal, tmp_path, monkeypatch):
    """The audit trail is the point: a rejection has to be recoverable from
    the ticket's event log, not just from disk state."""
    monkeypatch.setenv("TICKET_EVENTS_PATH", str(tmp_path / "ticket_events.jsonl"))
    client = _client()

    response = client.post(
        "/api/s3/reject",
        json={
            "proposal_id": "prop-1",
            "file_path": "created.py",
            "reason": "Out of scope for this CR",
            "ticket_number": "AMS-101",
        },
    )

    assert response.status_code == 200
    assert response.json()["rejected_files"] == {"created.py": "Out of scope for this CR"}

    events = client.get("/api/s3/ticket-events?ticket_number=AMS-101").json()["events"]
    rejected = [e for e in events if e["action"] == "code_change_rejected"]
    assert len(rejected) == 1
    assert rejected[0]["actor"] == "human"
    assert "created.py — Out of scope for this CR" == rejected[0]["detail"]


def test_reject_unknown_file_returns_502(staged_proposal):
    response = _client().post(
        "/api/s3/reject", json={"proposal_id": "prop-1", "file_path": "nope.py"}
    )
    assert response.status_code == 502


def test_revert_endpoint_restores_and_reports(staged_proposal, tmp_path, monkeypatch):
    monkeypatch.setenv("TICKET_EVENTS_PATH", str(tmp_path / "ticket_events.jsonl"))
    repo_root, _ = staged_proposal
    client = _client()

    client.post("/api/s3/apply", json={"proposal_id": "prop-1", "ticket_number": "AMS-101"})
    assert (repo_root / "existing.py").read_text() == "CHANGED = 1\n"

    response = client.post(
        "/api/s3/revert", json={"proposal_id": "prop-1", "ticket_number": "AMS-101"}
    )

    assert response.status_code == 200
    assert response.json()["reverted_files"] == ["created.py", "existing.py"]
    assert (repo_root / "existing.py").read_text() == "ORIGINAL = 1\n"
    assert not (repo_root / "created.py").exists()

    events = client.get("/api/s3/ticket-events?ticket_number=AMS-101").json()["events"]
    assert any(e["action"] == "code_change_reverted" for e in events)


def test_revert_without_an_apply_returns_502(staged_proposal):
    response = _client().post("/api/s3/revert", json={"proposal_id": "prop-1"})
    assert response.status_code == 502
