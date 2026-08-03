"""Test-suite-wide guards.

Kept deliberately small: this file exists for things that must be true of
*every* test, not for shared fixtures a couple of modules happen to want.
"""

from __future__ import annotations

import pytest

from s3_enhancement import admin_ops


@pytest.fixture(autouse=True)
def _no_real_process_control(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never start or stop a real service from the test suite.

    `/s3/apply` restarts the target application so the running process picks up
    the code that was just applied (see the apply handler). That is correct in
    the app and wrong in a test run: `pytest tests/` would stop and start
    EnrolDirect and ClaimsPortal on the developer's machine, fight with whatever
    they had running for a rehearsal, and leave services up that were down
    before. It bit on the first run of the restart change — a unit test spawned
    a real uvicorn on :8083.

    Autouse and suite-wide rather than patched per test, because the failure
    mode is silent: a new test that happens to reach apply would start doing
    process control without anybody noticing until a rehearsal broke. A test
    that specifically wants to exercise restart behaviour should patch
    `admin_ops.restart_application` itself with an explicit fake.
    """
    monkeypatch.setattr(admin_ops, "restart_application", lambda app_id: [])
