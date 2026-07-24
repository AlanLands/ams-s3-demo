from __future__ import annotations

from common.ticket_events import (
    clear_events,
    events_for,
    events_log_marker,
    record_event,
    tickets_with_action_detail,
)


def test_missing_events_file_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("TICKET_EVENTS_PATH", str(tmp_path / "missing.jsonl"))

    assert events_for("INC000001") == []


def test_append_read_filter_and_order_round_trip(tmp_path, monkeypatch):
    path = tmp_path / "ticket_events.jsonl"
    monkeypatch.setenv("TICKET_EVENTS_PATH", str(path))

    record_event("INC000001", "system", "created", "opened")
    record_event("INC000002", "ai", "triage", "other ticket")
    record_event("INC000001", "human", "approved_resolution", "reviewed")

    events = events_for("INC000001")

    assert [event["action"] for event in events] == ["created", "approved_resolution"]
    assert [event["actor"] for event in events] == ["system", "human"]
    assert events[0]["detail"] == "opened"
    assert events[1]["detail"] == "reviewed"


def test_record_event_is_idempotent_across_session_resets(tmp_path, monkeypatch):
    """A Streamlit page reload re-runs the pipeline with fresh session_state,
    so the caller's in-memory dedup can't be trusted — record_event() itself
    must refuse to duplicate an identical (ticket, actor, action, detail)."""
    path = tmp_path / "ticket_events.jsonl"
    monkeypatch.setenv("TICKET_EVENTS_PATH", str(path))

    record_event("INC000001", "system", "created", "opened")
    record_event("INC000001", "system", "created", "opened")  # simulated reload
    record_event("INC000001", "ai", "triage", "P2 / Batch")

    events = events_for("INC000001")
    assert [(e["actor"], e["action"]) for e in events] == [
        ("system", "created"),
        ("ai", "triage"),
    ]


def test_record_event_allows_same_action_with_different_detail(tmp_path, monkeypatch):
    path = tmp_path / "ticket_events.jsonl"
    monkeypatch.setenv("TICKET_EVENTS_PATH", str(path))

    record_event("INC000001", "ai", "triage", "P2 / Batch")
    record_event("INC000001", "ai", "triage", "P1 / Batch")  # genuinely re-triaged

    events = events_for("INC000001")
    assert [e["detail"] for e in events] == ["P2 / Batch", "P1 / Batch"]


def test_tickets_with_action_detail_filters_on_both(tmp_path, monkeypatch):
    path = tmp_path / "ticket_events.jsonl"
    monkeypatch.setenv("TICKET_EVENTS_PATH", str(path))

    record_event("INC000001", "ai", "engineer_assigned", "Jordan Blake")
    record_event("INC000002", "ai", "engineer_assigned", "Meera Iyer")
    record_event("INC000003", "ai", "engineer_assigned", "Jordan Blake")

    assert tickets_with_action_detail("engineer_assigned", "Jordan Blake") == {
        "INC000001",
        "INC000003",
    }
    assert tickets_with_action_detail("engineer_assigned", "Meera Iyer") == {"INC000002"}
    assert tickets_with_action_detail("engineer_assigned", "Nobody") == set()


def test_clear_events_removes_file(tmp_path, monkeypatch):
    path = tmp_path / "ticket_events.jsonl"
    monkeypatch.setenv("TICKET_EVENTS_PATH", str(path))
    record_event("INC000001", "system", "created")
    assert path.exists()

    clear_events()

    assert not path.exists()
    assert events_for("INC000001") == []


def test_events_log_marker_missing_file_returns_zero(tmp_path, monkeypatch):
    monkeypatch.setenv("TICKET_RESET_MARKER_PATH", str(tmp_path / "missing"))

    assert events_log_marker() == "0"


def test_events_log_marker_reads_marker_file_contents(tmp_path, monkeypatch):
    marker_path = tmp_path / ".s3_reset_marker"
    marker_path.write_text("12345\n", encoding="utf-8")
    monkeypatch.setenv("TICKET_RESET_MARKER_PATH", str(marker_path))

    assert events_log_marker() == "12345"


def test_events_log_marker_unaffected_by_recording_events(tmp_path, monkeypatch):
    """The marker must only change on an explicit reset (demo/reset_s3.sh
    writing a fresh marker file) — never as a side effect of normal event
    recording, or every reload would look like a reset happened."""
    events_path = tmp_path / "ticket_events.jsonl"
    marker_path = tmp_path / ".s3_reset_marker"
    marker_path.write_text("1", encoding="utf-8")
    monkeypatch.setenv("TICKET_EVENTS_PATH", str(events_path))
    monkeypatch.setenv("TICKET_RESET_MARKER_PATH", str(marker_path))

    before = events_log_marker()
    record_event("INC000001", "system", "created")
    record_event("INC000001", "ai", "triage", "P2 / Batch")

    assert events_log_marker() == before
