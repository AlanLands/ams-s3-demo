"""A failed live harness run must still leave a status.json behind — the
whole point of the failure artifact is that /s3/harness/latest can show the
crashed run instead of 404ing as if it never happened."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from s3_enhancement import harness


def _fake_target() -> SimpleNamespace:
    return SimpleNamespace(harness_expected_files=["mockapp/core/models.py"])


def test_run_live_writes_failed_status_on_harness_error(tmp_path, monkeypatch):
    monkeypatch.setattr(harness, "OUT_ROOT", tmp_path)
    monkeypatch.setattr(harness, "render_cr", lambda tier_name, target=None: "CR text")
    monkeypatch.setattr(
        harness, "build_command", lambda tier_name, cr_text: ("fake-cli", ["fake-cli"])
    )
    monkeypatch.setattr(harness, "_untracked_paths", lambda: set())
    monkeypatch.setattr(harness, "_tracked_content_hashes", lambda: {})
    monkeypatch.setattr(harness, "_snapshot_expected_files", lambda expected: {})

    def boom(argv, log_path, timeout):
        raise harness.HarnessError("harness run exceeded 5s timeout and was killed")

    monkeypatch.setattr(harness, "_stream_process", boom)

    with pytest.raises(harness.HarnessError):
        harness._run_live("Elite", _fake_target())

    status_files = list(tmp_path.glob("*/harness/status.json"))
    assert len(status_files) == 1
    status = json.loads(status_files[0].read_text(encoding="utf-8"))
    assert status["status"] == "failed"
    assert "timeout" in status["error"]
    assert status["tier_name"] == "Elite"


def test_run_live_success_status_is_marked_ok(tmp_path, monkeypatch):
    monkeypatch.setattr(harness, "OUT_ROOT", tmp_path)
    monkeypatch.setattr(harness, "render_cr", lambda tier_name, target=None: "CR text")
    monkeypatch.setattr(
        harness, "build_command", lambda tier_name, cr_text: ("fake-cli", ["fake-cli"])
    )
    # One expected file "changes" during the run so the touched-files check passes.
    tracked = iter([{"mockapp/core/models.py": "before"}, {"mockapp/core/models.py": "after"}])
    monkeypatch.setattr(harness, "_untracked_paths", lambda: set())
    monkeypatch.setattr(harness, "_tracked_content_hashes", lambda: next(tracked))
    monkeypatch.setattr(harness, "_snapshot_expected_files", lambda expected: {})
    monkeypatch.setattr(harness, "_stream_process", lambda argv, log_path, timeout: (0, "log"))
    monkeypatch.setattr(
        harness, "_run_pytest", lambda: SimpleNamespace(returncode=0, stdout="", stderr="")
    )
    monkeypatch.setattr(harness, "_validate_content", lambda tier_name: None)
    monkeypatch.setattr(harness, "_build_diff", lambda before, expected: "diff text")

    result = harness._run_live("Elite", _fake_target())

    assert result.files_changed == ["mockapp/core/models.py"]
    status_files = list(tmp_path.glob("*/harness/status.json"))
    assert len(status_files) == 1
    status = json.loads(status_files[0].read_text(encoding="utf-8"))
    assert status["status"] == "ok"
    assert status["files_changed"] == ["mockapp/core/models.py"]
