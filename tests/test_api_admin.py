"""The admin panel's guarantees, not just its happy path.

The panel puts `demo/reset_s3.sh` behind a button, and those scripts restore
source with `git checkout HEAD -- …`. So the tests that matter here are the
refusals: a source scope must 409 while the tree is dirty, must 409 while the
paths it checks out are missing from HEAD (the live `apps/` -> `repos/` state
today), the console must never be a controllable service id, and nothing may
be reported up/started/stopped that was not actually observed on the port.

Every filesystem test runs against a throwaway git repo under `tmp_path` via
`S3_ADMIN_REPO_ROOT`. Nothing here runs a reset script, `git checkout`,
`git stash` or anything else that writes to the real working tree — which
currently holds a few hundred uncommitted files of unrelated work.
"""

from __future__ import annotations

import ast
import socket
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.console.api.main import app
from common.roster import PASSCODE_BY_NAME
from s3_enhancement import admin_ops

REAL_RUN = subprocess.run


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _client(name: str = "Manager") -> TestClient:
    client = TestClient(app)
    response = client.post(
        "/api/auth/login", json={"name": name, "passcode": PASSCODE_BY_NAME[name]}
    )
    assert response.status_code == 200, response.text
    return client


def _write(root: Path, rel: str, text: str = "x\n") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return REAL_RUN(
        [
            "git",
            "-c",
            "user.email=demo@example.invalid",
            "-c",
            "user.name=Demo",
            *args,
        ],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=True,
    )


# Every path the three source scopes touch, so a "clean tree" fixture really
# is clean for all of them.
_SOURCE_PATHS = (
    "repos/policycore/app.py",
    "repos/policycore/core/models.py",
    "repos/policycore/core/db.py",
    "repos/policycore/core/amendments.py",
    "repos/documenthub/feed.py",
    "repos/documenthub/wording.py",
    "repos/documenthub/enclosures.py",
    "repos/documenthub/packs.py",
    "repos/documenthub/main.py",
    "repos/enroldirect/applicants.py",
    "repos/enroldirect/eligibility.py",
    "repos/enroldirect/enrolments.py",
    "repos/enroldirect/main.py",
)

_SCRIPTS = (
    "demo/reset_s3.sh",
    "demo/reset_s3_endorsement.sh",
    "demo/reset_s3_documenthub.sh",
    "demo/reset_s3_enroldirect.sh",
    "demo/run_mockapp.sh",
    "apps/run-documenthub.sh",
    "apps/run-enroldirect.sh",
)


def _make_repo(tmp_path: Path, *, layout: tuple[str, ...] = _SOURCE_PATHS) -> Path:
    """A throwaway repo whose HEAD carries `layout` and nothing else."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _write(root, ".gitignore", ".cache/\ndata/*\ns3_enhancement/out/\nlogs/\n")
    for rel in layout:
        _write(root, rel)
    for rel in _SCRIPTS:
        _write(root, rel, "#!/usr/bin/env bash\nexit 0\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "baseline")
    return root


@pytest.fixture()
def clean_repo(tmp_path, monkeypatch) -> Path:
    root = _make_repo(tmp_path)
    monkeypatch.setenv(admin_ops.REPO_ROOT_ENV, str(root))
    return root


@pytest.fixture()
def head_bug_repo(tmp_path, monkeypatch) -> Path:
    """The repo in the state this project is actually in: the targets moved
    from `apps/` to `repos/` in the working tree, but the move is uncommitted,
    so HEAD still carries the old paths and every
    `git checkout HEAD -- repos/...` in the reset scripts fails."""
    old_layout = tuple(p.replace("repos/", "apps/", 1) for p in _SOURCE_PATHS)
    root = _make_repo(tmp_path, layout=old_layout)
    for rel in _SOURCE_PATHS:
        _write(root, rel)
    monkeypatch.setenv(admin_ops.REPO_ROOT_ENV, str(root))
    return root


# ---------------------------------------------------------------------------
# role gate
# ---------------------------------------------------------------------------

ADMIN_GETS = ["/api/admin/status", "/api/admin/logs", "/api/admin/reset/tickets/preview"]


@pytest.mark.parametrize("path", ADMIN_GETS)
def test_admin_routes_401_without_a_session(path):
    assert TestClient(app).get(path).status_code == 401


@pytest.mark.parametrize("path", ADMIN_GETS)
def test_admin_routes_403_for_an_engineer(path, clean_repo):
    assert _client("Ravi Kumar").get(path).status_code == 403


def test_engineer_cannot_reset_or_control_services_or_onboard(clean_repo):
    client = _client("Ravi Kumar")
    reset = client.post("/api/admin/reset", json={"scope": "tickets", "confirm": True})
    assert reset.status_code == 403
    assert client.post("/api/admin/services/enroldirect/start").status_code == 403
    assert client.post("/api/admin/repos/onboard", json={"name": "x"}).status_code == 403
    assert client.delete("/api/admin/logs").status_code == 403


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


def test_status_shape_and_reset_safe_on_a_clean_tree(clean_repo):
    body = _client().get("/api/admin/status").json()

    assert body["branch"] == "main"
    assert body["is_default_branch"] is True
    assert body["dirty_file_count"] == 0
    assert body["reset_safe"] is True
    assert body["reset_blocked_reason"] is None

    assert [s["id"] for s in body["services"]] == [
        "policycore",
        "enroldirect",
        "documenthub",
    ]
    for service in body["services"]:
        assert set(service) == {"id", "label", "port", "up", "command"}
        assert isinstance(service["up"], bool)

    assert body["targets"], "the three built-in targets must be listed"
    for target in body["targets"]:
        assert set(target) == {
            "target_id",
            "display_name",
            "repo",
            "story",
            "discovered",
            "has_recording",
        }

    assert set(body["state"]) == {
        "staged_proposals",
        "ticket_events",
        "llm_cache_entries",
        "generated_test_files",
    }


def test_status_is_not_default_branch_off_main(clean_repo):
    _git(clean_repo, "checkout", "-qb", "s3-console-stage-routes")
    body = _client().get("/api/admin/status").json()
    assert body["branch"] == "s3-console-stage-routes"
    assert body["is_default_branch"] is False


def test_dirty_tree_makes_reset_unsafe_and_names_the_files(clean_repo):
    _write(clean_repo, "repos/policycore/app.py", "edited by a human\n")
    body = _client().get("/api/admin/status").json()

    assert body["reset_safe"] is False
    assert body["dirty_file_count"] == 1
    assert "repos/policycore/app.py" in body["reset_blocked_reason"]
    assert "uncommitted" in body["reset_blocked_reason"]


def test_head_path_bug_is_named_rather_than_left_to_fail_as_a_git_error(head_bug_repo):
    """The live breakage: `git checkout HEAD -- repos/policycore/app.py` dies
    with "pathspec did not match" because the repos/ move is uncommitted."""
    missing = admin_ops.head_missing_paths(["policycore"])
    assert missing == [
        "repos/policycore/app.py",
        "repos/policycore/core/amendments.py",
        "repos/policycore/core/db.py",
        "repos/policycore/core/models.py",
    ]
    # Verified the same way the reset script would discover it.
    assert admin_ops.head_has_path("apps/policycore/app.py") is True
    assert admin_ops.head_has_path("repos/policycore/app.py") is False

    body = _client().get("/api/admin/status").json()
    reason = body["reset_blocked_reason"]
    assert body["reset_safe"] is False
    assert "do not exist in HEAD" in reason
    assert "repos/policycore/app.py" in reason
    assert "pathspec did not match" in reason


# ---------------------------------------------------------------------------
# preview
# ---------------------------------------------------------------------------


def test_preview_lists_restores_deletes_and_dirty(clean_repo):
    _write(clean_repo, "repos/policycore/core/db.py", "edited\n")
    _write(clean_repo, "tests/test_s3_tier_upgrade.py", "generated\n")

    body = _client().get("/api/admin/reset/policycore/preview").json()

    assert body["scope"] == "policycore"
    assert set(body) == {"scope", "restores", "deletes", "dirty"}
    assert "repos/policycore/app.py" in body["restores"]
    assert "repos/policycore/core/amendments.py" in body["restores"]
    assert "tests/test_s3_tier_upgrade.py" in body["deletes"]
    # Only files that exist are listed as deletes.
    assert "repos/policycore/core/tiers.py" not in body["deletes"]
    # The edited source file is dirty; the untracked *generated* test the
    # scope exists to remove is not — see admin_ops.dirty_among.
    assert body["dirty"] == ["repos/policycore/core/db.py"]


def test_a_tracked_and_edited_generated_test_still_counts_as_dirty(clean_repo):
    """The untracked-generated-file carve-out must not swallow real work: a
    file at a generated path that git *tracks* and that has been edited is
    somebody's change, and the scope would delete it."""
    _write(clean_repo, "tests/test_s3_prospect_access.py", "committed\n")
    _git(clean_repo, "add", "-A")
    _git(clean_repo, "commit", "-qm", "track the generated suite")
    _write(clean_repo, "tests/test_s3_prospect_access.py", "hand-edited\n")

    body = _client().get("/api/admin/reset/enroldirect/preview").json()
    assert body["dirty"] == ["tests/test_s3_prospect_access.py"]

    response = _client().post("/api/admin/reset", json={"scope": "enroldirect", "confirm": True})
    assert response.status_code == 409


def test_preview_for_documenthub_lists_the_baseline_restore_set(clean_repo):
    body = _client().get("/api/admin/reset/documenthub/preview").json()
    assert body["restores"] == sorted(
        [
            "repos/documenthub/wording.py",
            "repos/documenthub/enclosures.py",
            "repos/documenthub/packs.py",
        ]
    )
    assert body["dirty"] == []


def test_preview_of_a_delete_only_scope_ignores_gitignored_state(clean_repo):
    _write(clean_repo, "data/ticket_events.jsonl", '{"a":1}\n')
    body = _client().get("/api/admin/reset/tickets/preview").json()
    assert body["restores"] == []
    assert body["deletes"] == ["data/ticket_events.jsonl"]
    # Gitignored generated state is not uncommitted *work*.
    assert body["dirty"] == []


def test_unknown_scope_is_404(clean_repo):
    assert _client().get("/api/admin/reset/everything/preview").status_code == 404


# ---------------------------------------------------------------------------
# reset
# ---------------------------------------------------------------------------


def test_there_is_no_everything_scope(clean_repo):
    assert set(admin_ops.SCOPES) == {
        "policycore",
        "documenthub",
        "enroldirect",
        "tickets",
        "logs",
        "proposals",
        "caches",
    }
    response = _client().post("/api/admin/reset", json={"scope": "everything", "confirm": True})
    assert response.status_code == 404


def test_reset_without_confirm_is_400(clean_repo):
    response = _client().post("/api/admin/reset", json={"scope": "tickets"})
    assert response.status_code == 400
    assert "confirm" in response.json()["detail"]


def test_source_reset_409s_when_the_tree_is_dirty(clean_repo):
    _write(clean_repo, "repos/enroldirect/eligibility.py", "half-finished work\n")
    response = _client().post("/api/admin/reset", json={"scope": "enroldirect", "confirm": True})
    assert response.status_code == 409
    assert "repos/enroldirect/eligibility.py" in response.json()["detail"]


def test_source_reset_409s_on_the_head_path_bug(head_bug_repo):
    response = _client().post("/api/admin/reset", json={"scope": "policycore", "confirm": True})
    assert response.status_code == 409
    assert "do not exist in HEAD" in response.json()["detail"]


@pytest.mark.parametrize("scope", ["tickets", "logs", "proposals", "caches"])
def test_delete_only_scopes_stay_allowed_on_a_dirty_tree(scope, clean_repo):
    _write(clean_repo, "repos/policycore/app.py", "dirty\n")
    _write(clean_repo, "data/ticket_events.jsonl", '{"a":1}\n')
    (clean_repo / "s3_enhancement" / "out" / "prop-1").mkdir(parents=True)
    (clean_repo / ".cache" / "llm").mkdir(parents=True)

    response = _client().post("/api/admin/reset", json={"scope": scope, "confirm": True})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["scope"] == scope
    assert body["simulated"] is False
    assert isinstance(body["ran"], list)


def test_tickets_reset_really_deletes_and_bumps_the_reset_marker(clean_repo):
    events = _write(clean_repo, "data/ticket_events.jsonl", '{"a":1}\n')
    body = _client().post("/api/admin/reset", json={"scope": "tickets", "confirm": True}).json()

    assert body["ran"] == ["rm -f data/ticket_events.jsonl"]
    assert not events.exists()
    assert (clean_repo / "data" / ".s3_reset_marker").is_file()


def test_proposals_reset_empties_out_but_keeps_the_directory(clean_repo):
    (clean_repo / "s3_enhancement" / "out" / "prop-1").mkdir(parents=True)
    _write(clean_repo, "s3_enhancement/out/prop-1/scm.json", "{}")
    _write(clean_repo, "s3_enhancement/out/loose.json", "{}")

    _client().post("/api/admin/reset", json={"scope": "proposals", "confirm": True})

    out_dir = clean_repo / "s3_enhancement" / "out"
    assert out_dir.is_dir()
    assert list(out_dir.iterdir()) == []


def test_caches_reset_never_touches_the_committed_replay_recordings(clean_repo):
    (clean_repo / ".cache" / "llm").mkdir(parents=True)
    _write(clean_repo, ".cache/llm/abc.json", "{}")
    recording = _write(clean_repo, "s3_enhancement/cache/s3_codegen.json", "{}")

    _client().post("/api/admin/reset", json={"scope": "caches", "confirm": True})

    assert not (clean_repo / ".cache" / "llm").exists()
    assert recording.is_file(), "committed replay recordings must survive a cache reset"
    # The relevance embedding index is deliberately out of scope too: dropping
    # it can mean live embedding calls mid-demo.
    assert ".cache/vectordb" not in admin_ops.SCOPES["caches"].delete_trees


def test_clean_tree_runs_both_policycore_scripts_by_absolute_path_no_shell(clean_repo, monkeypatch):
    calls: list[tuple] = []

    def fake_run(argv, **kwargs):
        if Path(argv[0]).name == "git":
            return REAL_RUN(argv, **kwargs)
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    body = _client().post("/api/admin/reset", json={"scope": "policycore", "confirm": True}).json()

    assert body["ran"] == ["demo/reset_s3.sh", "demo/reset_s3_endorsement.sh"]
    assert body["simulated"] is False
    assert len(calls) == 2
    for argv, kwargs in calls:
        assert isinstance(argv, list) and len(argv) == 2
        assert Path(argv[0]).name == "bash"
        assert Path(argv[1]).is_absolute()
        assert kwargs.get("shell", False) is False


def test_a_failing_reset_script_surfaces_as_500_with_its_output(clean_repo, monkeypatch):
    def fake_run(argv, **kwargs):
        if Path(argv[0]).name == "git":
            return REAL_RUN(argv, **kwargs)
        return subprocess.CompletedProcess(argv, 1, "", "fatal: pathspec did not match\n")

    monkeypatch.setattr(subprocess, "run", fake_run)
    response = _client().post("/api/admin/reset", json={"scope": "enroldirect", "confirm": True})
    assert response.status_code == 500
    assert "pathspec did not match" in response.json()["detail"]


# ---------------------------------------------------------------------------
# structural: this module never writes to the working tree via git
# ---------------------------------------------------------------------------


def test_admin_ops_never_runs_a_git_write_command():
    """Asserted on the parsed AST, the same way tests/test_s3_scm.py guards
    scm.py: the module's prose legitimately says "checkout" and "stash", so a
    substring search would be both noisy and unfalsifiable. Every git write in
    a reset comes from the reset scripts, which are gated; none may come from
    here, where nothing gates them.
    """
    source = Path(admin_ops.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden = {"checkout", "stash", "reset", "clean", "restore", "commit", "push", "rm"}

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
        if name != "_git":
            continue
        assert node.args, "_git() called with no subcommand"
        first = node.args[0]
        assert isinstance(first, ast.Constant), "git subcommand must be a literal, never built"
        assert first.value not in forbidden, f"admin_ops must not run `git {first.value}`"


def test_admin_ops_never_uses_a_shell():
    source = Path(admin_ops.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for keyword in node.keywords:
                if keyword.arg == "shell":
                    assert isinstance(keyword.value, ast.Constant) and keyword.value.value is False
        if isinstance(node, ast.Attribute) and node.attr in {"system", "popen"}:
            value = node.value
            assert not (isinstance(value, ast.Name) and value.id == "os")


# ---------------------------------------------------------------------------
# services
# ---------------------------------------------------------------------------


def test_up_is_a_real_tcp_probe(clean_repo):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        port = sock.getsockname()[1]
        assert admin_ops.port_open(port) is True
    assert admin_ops.port_open(port) is False


def test_there_is_no_service_id_for_the_console(clean_repo):
    client = _client()
    assert "console" not in admin_ops.SERVICES_BY_ID
    for service_id in ["console", "console-api", "api", "web", "ui", "admin"]:
        response = client.post(f"/api/admin/services/{service_id}/restart")
        assert response.status_code == 400, service_id
        assert "cannot control the process serving this request" in response.json()["detail"]


def test_unknown_service_and_action(clean_repo):
    client = _client()
    assert client.post("/api/admin/services/nope/start").status_code == 404
    assert client.post("/api/admin/services/enroldirect/detonate").status_code == 400


def test_start_reports_already_up_without_spawning(clean_repo, monkeypatch):
    monkeypatch.setattr(admin_ops, "port_open", lambda port, **kw: True)

    def explode(*a, **kw):  # pragma: no cover - must not be reached
        raise AssertionError("must not spawn a process for a service already up")

    monkeypatch.setattr(subprocess, "Popen", explode)
    body = _client().post("/api/admin/services/enroldirect/start").json()
    assert set(body) == {"id", "action", "ok", "detail", "command"}
    assert body["id"] == "enroldirect"
    assert body["action"] == "start"
    assert body["ok"] is True
    assert body["command"] == "apps/run-enroldirect.sh"
    assert "Already up" in body["detail"]


def test_start_reports_failure_with_the_command_when_process_control_is_off(
    clean_repo, monkeypatch
):
    monkeypatch.setenv(admin_ops.PROCESS_CONTROL_ENV, "off")
    monkeypatch.setattr(admin_ops, "port_open", lambda port, **kw: False)

    def explode(*a, **kw):  # pragma: no cover - must not be reached
        raise AssertionError("process control is off; nothing may be spawned")

    monkeypatch.setattr(subprocess, "Popen", explode)
    body = _client().post("/api/admin/services/policycore/start").json()

    assert body["ok"] is False
    assert body["command"] == "demo/run_mockapp.sh"
    assert "demo/run_mockapp.sh" in body["detail"]


def test_start_that_never_binds_the_port_reports_failure_not_success(clean_repo, monkeypatch):
    """The Popen returning is not evidence. The port is."""
    monkeypatch.setattr(admin_ops, "port_open", lambda port, **kw: False)
    monkeypatch.setattr(admin_ops, "_await_port", lambda port, want_open, timeout=12.0: False)

    class FakeProc:
        pid = 4242

    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: FakeProc())
    body = _client().post("/api/admin/services/enroldirect/start").json()

    assert body["ok"] is False
    assert "nothing is listening" in body["detail"]
    assert body["command"] == "apps/run-enroldirect.sh"


def test_stop_of_a_process_the_console_did_not_start_is_an_honest_no(clean_repo, monkeypatch):
    monkeypatch.setattr(admin_ops, "port_open", lambda port, **kw: True)

    def explode(*a, **kw):  # pragma: no cover - must not be reached
        raise AssertionError("must not signal a pid it does not own")

    monkeypatch.setattr(admin_ops.os, "kill", explode)
    body = _client().post("/api/admin/services/documenthub/stop").json()

    assert body["ok"] is False
    assert "did not start it" in body["detail"]
    assert body["command"] == "apps/run-documenthub.sh"


def test_stop_of_something_already_down_is_ok(clean_repo, monkeypatch):
    monkeypatch.setattr(admin_ops, "port_open", lambda port, **kw: False)
    body = _client().post("/api/admin/services/enroldirect/stop").json()
    assert body["ok"] is True
    assert "Already down" in body["detail"]


def test_service_port_follows_dotenv(clean_repo, monkeypatch):
    monkeypatch.delenv("ENROLDIRECT_PORT", raising=False)
    _write(clean_repo, ".env", "ENROLDIRECT_PORT=9099\n")
    assert admin_ops.service_port(admin_ops.SERVICES_BY_ID["enroldirect"]) == 9099


# ---------------------------------------------------------------------------
# onboarding
# ---------------------------------------------------------------------------

_ONBOARD = {
    "name": "samplebenefits",
    "display_name": "SampleBenefits — annual limit",
    "target_id": "samplebenefits-annual-limit",
    "cache_namespace": "samplebenefits_annual_limit",
    "story": None,
    "core_files": ["repos/samplebenefits/service.py"],
    "codegen_allowlist": ["repos/samplebenefits/service.py"],
    "testgen_allowlist": ["tests/test_s3_samplebenefits.py"],
    "regression_paths": [],
    "post_apply_command": [],
    "dry_run": True,
}


def test_onboard_dry_run_validates_without_writing(clean_repo):
    body = _client().post("/api/admin/repos/onboard", json=_ONBOARD).json()

    assert body["ok"] is True
    assert body["errors"] == []
    assert body["written"] is False
    assert body["manifest_path"] == "repos/samplebenefits/.s3targets.json"
    assert body["manifest"]["targets"][0]["target_id"] == "samplebenefits-annual-limit"
    assert not (clean_repo / "repos" / "samplebenefits").exists()
    assert any("does not exist yet" in w for w in body["warnings"])
    assert any("dry_run" in w for w in body["warnings"])


def test_onboard_write_says_a_console_restart_is_needed(clean_repo):
    payload = {**_ONBOARD, "dry_run": False}
    body = _client().post("/api/admin/repos/onboard", json=payload).json()

    assert body["ok"] is True
    assert body["written"] is True
    manifest = clean_repo / "repos" / "samplebenefits" / ".s3targets.json"
    assert manifest.is_file()
    assert "samplebenefits-annual-limit" in manifest.read_text(encoding="utf-8")
    assert any("restarted" in w and "not live yet" in w for w in body["warnings"])
    # It really is not registered yet.
    assert "samplebenefits-annual-limit" not in {
        t.target_id for t in __import__("s3_enhancement.targets", fromlist=["x"]).all_targets()
    }


def test_onboard_refuses_to_overwrite_an_existing_manifest(clean_repo):
    payload = {**_ONBOARD, "dry_run": False}
    assert _client().post("/api/admin/repos/onboard", json=payload).json()["written"] is True
    second = _client().post("/api/admin/repos/onboard", json=payload).json()
    assert second["ok"] is False
    assert second["written"] is False
    assert any("already exists" in e for e in second["errors"])


@pytest.mark.parametrize(
    "name",
    ["../escape", "nested/name", "back\\slash", "/absolute", "", "..", ".hidden", "C:name"],
)
def test_onboard_rejects_an_unsafe_repo_name(name, clean_repo):
    body = _client().post("/api/admin/repos/onboard", json={**_ONBOARD, "name": name}).json()
    assert body["ok"] is False
    assert body["errors"]
    assert body["written"] is False
    # No directory is created anywhere — inside repos/ or, for a traversal
    # attempt, above it.
    assert sorted(p.name for p in (clean_repo / "repos").iterdir()) == [
        "documenthub",
        "enroldirect",
        "policycore",
    ]
    assert not (clean_repo.parent / "escape").exists()


def test_onboard_rejects_a_registered_target_id_and_namespace(clean_repo):
    from s3_enhancement.targets import ENROLDIRECT_TARGET_ID

    body = _client().post(
        "/api/admin/repos/onboard",
        json={**_ONBOARD, "target_id": ENROLDIRECT_TARGET_ID, "dry_run": False},
    ).json()
    assert body["ok"] is False
    assert any("already registered" in e for e in body["errors"])

    body = _client().post(
        "/api/admin/repos/onboard",
        json={**_ONBOARD, "cache_namespace": "enroldirect_prospect_access", "dry_run": False},
    ).json()
    assert body["ok"] is False
    assert any("already used by target" in e for e in body["errors"])
    assert not (clean_repo / "repos" / "samplebenefits").exists()


def test_onboard_surfaces_discovery_manifest_errors(clean_repo):
    """Validation goes through discovery._build_target, so its rules — not a
    second copy of them — are what a bad manifest hits."""
    body = _client().post(
        "/api/admin/repos/onboard", json={**_ONBOARD, "cache_namespace": ""}
    ).json()
    assert body["ok"] is False
    assert any("cache_namespace" in e for e in body["errors"])

    body = _client().post(
        "/api/admin/repos/onboard", json={**_ONBOARD, "story": "stories/US-DOES-NOT-EXIST.md"}
    ).json()
    assert body["ok"] is False
    assert any("does not exist" in e for e in body["errors"])


def test_onboard_warns_about_a_missing_regression_suite(clean_repo):
    body = _client().post("/api/admin/repos/onboard", json=_ONBOARD).json()
    assert any("regression_paths" in w for w in body["warnings"])
    assert any("live LLM call" in w for w in body["warnings"])


# ---------------------------------------------------------------------------
# logs
# ---------------------------------------------------------------------------


def test_logs_listing_and_deletion(clean_repo):
    _write(clean_repo, "data/ticket_events.jsonl", '{"a":1}\n{"b":2}\n')
    _write(clean_repo, "logs/enroldirect.log", "boot\n")
    client = _client()

    listing = client.get("/api/admin/logs").json()
    by_path = {f["path"]: f for f in listing["files"]}
    assert by_path["data/ticket_events.jsonl"]["lines"] == 2
    assert by_path["data/ticket_events.jsonl"]["bytes"] == 16
    assert "logs/enroldirect.log" in by_path

    deleted = client.delete("/api/admin/logs").json()
    assert sorted(deleted["deleted"]) == ["data/ticket_events.jsonl", "logs/enroldirect.log"]
    assert deleted["bytes_freed"] == 21
    assert client.get("/api/admin/logs").json() == {"files": []}
