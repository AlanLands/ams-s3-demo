from pathlib import Path

import pytest

from common import servicenow_client as sn
from common.ticket_events import events_for


@pytest.fixture(autouse=True)
def _isolated_stores(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SN_MOCK_STORE_PATH", str(tmp_path / "servicenow_mock.json"))
    monkeypatch.setenv("TICKET_EVENTS_PATH", str(tmp_path / "ticket_events.jsonl"))
    monkeypatch.delenv("SN_MODE", raising=False)


def test_create_problem_persists_and_links_incidents():
    record = sn.create_problem("PRB0002001", "Recurring batch failure", ["INC001", "INC002"])

    assert record.table == "problem"
    assert record.state == "New"
    assert record.linked_records == ["INC001", "INC002"]
    assert len(record.work_notes) == 1

    reloaded = sn.get_record("PRB0002001")
    assert reloaded == record


def test_create_problem_is_idempotent_per_number():
    first = sn.create_problem("PRB0002001", "Recurring batch failure", ["INC001"])
    second = sn.create_problem("PRB0002001", "different text ignored", [])

    assert second == first
    assert len(sn.list_records()) == 1


def test_create_problem_records_audit_event():
    sn.create_problem("PRB0002001", "Recurring batch failure", ["INC001"])

    events = events_for("PRB0002001")
    assert any(e["action"] == "posted_to_servicenow" for e in events)


def test_add_work_note_appends_and_audits():
    sn.create_problem("PRB0002001", "Recurring batch failure", [])
    updated = sn.add_work_note("PRB0002001", "Fix shipped in release 2.4.1", "human")

    assert updated.work_notes[-1].text == "Fix shipped in release 2.4.1"
    assert updated.work_notes[-1].actor == "human"
    assert any(e["action"] == "work_note_added" for e in events_for("PRB0002001"))


def test_add_work_note_missing_record_raises():
    with pytest.raises(sn.SnError, match="No record"):
        sn.add_work_note("PRB0009999", "text", "human")


def test_add_work_note_empty_text_raises():
    sn.create_problem("PRB0002001", "x", [])
    with pytest.raises(sn.SnError, match="empty"):
        sn.add_work_note("PRB0002001", "   ", "human")


def test_ensure_incident_creates_shell_then_reuses():
    created = sn.ensure_incident("INC0012345", "Payment gateway timeout")
    assert created.table == "incident"

    sn.add_work_note("INC0012345", "Resolution applied", "human")
    reused = sn.ensure_incident("INC0012345")
    assert reused.short_description == "Payment gateway timeout"
    assert len(reused.work_notes) == 1


def test_list_records_newest_first():
    sn.create_problem("PRB0002001", "first", [])
    sn.ensure_incident("INC001", "second")

    numbers = [r.number for r in sn.list_records()]
    assert numbers == ["INC001", "PRB0002001"]


def test_get_record_missing_returns_none():
    assert sn.get_record("PRB0000000") is None


def test_live_mode_is_an_explicit_stub(monkeypatch):
    monkeypatch.setenv("SN_MODE", "live")
    with pytest.raises(sn.SnError, match="live"):
        sn.create_problem("PRB0002001", "x", [])
    with pytest.raises(sn.SnError, match="live"):
        sn.list_records()


def test_unknown_mode_raises(monkeypatch):
    monkeypatch.setenv("SN_MODE", "banana")
    with pytest.raises(sn.SnError, match="Unknown SN_MODE"):
        sn.list_records()


def test_clear_records_removes_store():
    sn.create_problem("PRB0002001", "x", [])
    sn.clear_records()
    assert sn.list_records() == []
