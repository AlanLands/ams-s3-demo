"""Verifies s3_enhancement/scm.py -- the modelled branch -> commit -> push flow
around Apply, its server-side test gate, and the guarantee that none of it runs
git.

The last one is the point of the module and is asserted structurally, not by
convention, the same way tests/test_autofix_no_git_writes.py protects the
autofix loop: the target apps live inside this repo, and demo/reset_s3*.sh
restores their baseline with `git checkout HEAD -- <paths>`. A real commit here
would make HEAD carry the user story, and the reset scripts would start silently
restoring the change instead of the baseline.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from s3_enhancement import scm

SCM_SOURCE = Path(scm.__file__)


@pytest.fixture(autouse=True)
def _isolated_out(tmp_path, monkeypatch):
    monkeypatch.setattr(scm, "OUT_ROOT", tmp_path / "out")


# --- the no-git-writes guarantee --------------------------------------------


def test_scm_module_imports_no_process_spawning_machinery():
    """No subprocess, os.system, or shutil.which anywhere in the module.

    Checked on the parsed import graph rather than by substring, because the
    module's docstring and its rendered transcript both legitimately contain the
    words "commit" and "push" — a text search would either miss the real risk or
    fire on the prose describing it.
    """
    tree = ast.parse(SCM_SOURCE.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    forbidden = {"subprocess", "os", "pty", "popen2", "commands", "sh", "git", "pygit2"}
    assert not (imported & forbidden), (
        f"{SCM_SOURCE.name} must never be able to run git — it imports "
        f"{sorted(imported & forbidden)}"
    )


def test_scm_module_calls_nothing_that_could_execute():
    """Belt and braces on the call graph: no `system`, `run`, `Popen`, `exec*`.

    An import guard alone would miss `__import__("subprocess")` or a call
    reached through an object handed in by a caller.
    """
    tree = ast.parse(SCM_SOURCE.read_text(encoding="utf-8"))
    forbidden_names = {
        "system",
        "Popen",
        "run",
        "call",
        "check_call",
        "check_output",
        "execv",
        "execvp",
        "spawn",
        "fork",
        "__import__",
        "eval",
        "exec",
    }
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name in forbidden_names:
            offenders.append(f"line {node.lineno}: {name}(...)")

    assert not offenders, (
        f"{SCM_SOURCE.name} must not be able to execute anything: " + "; ".join(offenders)
    )


def test_every_state_dict_declares_itself_simulated():
    """`simulated` is not a mode flag that could come back false — it is the
    truth about this module, on every response, so the console and the release
    record cannot present a modelled push as a deployment."""
    state = scm.open_branch("p1", "AMS-103", "claimsportal-claims-deductible")
    assert state.to_dict()["simulated"] is True
    scm.record_applied("p1", ["a.java"])
    state = scm.commit_branch("p1", "AMS-103: do the thing")
    assert state.to_dict()["simulated"] is True
    assert scm.push_branch("p1").to_dict()["simulated"] is True


# --- naming -----------------------------------------------------------------


def test_branch_name_pairs_the_ticket_with_the_target():
    assert (
        scm.branch_name_for("AMS-103", "claimsportal-claims-deductible")
        == "feature/AMS-103-claimsportal-claims-deductible"
    )


def test_branch_name_keeps_the_ticket_key_readable():
    """The Jira key stays upper-case: it is written that way on the board, and
    lower-casing it makes the branch harder to match back to the ticket."""
    assert scm.branch_name_for("AMS-103", "x").startswith("feature/AMS-103-")


def test_branch_name_slugifies_an_awkward_target_id():
    assert scm.branch_name_for("AMS-1", "Weird Target/Id!") == "feature/AMS-1-weird-target-id"


def test_branch_name_survives_a_missing_ticket():
    """Apply must still work off-ticket — the branch says so instead of
    producing `feature/-something`."""
    assert scm.branch_name_for("", "policycore") == "feature/no-ticket-policycore"


# --- the flow ---------------------------------------------------------------


def test_open_branch_is_idempotent():
    """A per-file apply calls this once per file; a second call must stay on the
    branch it already cut rather than resetting its history."""
    first = scm.open_branch("p1", "AMS-103", "t")
    scm.record_applied("p1", ["a.py"])
    second = scm.open_branch("p1", "AMS-103", "t")
    assert second.branch == first.branch
    assert second.staged_files == ["a.py"], "re-opening must not discard applied files"


def test_status_walks_the_flow():
    assert scm.open_branch("p1", "AMS-103", "t").status == "open"
    assert scm.record_applied("p1", ["a.py"]).status == "applied"
    assert scm.commit_branch("p1", "msg").status == "committed"
    assert scm.push_branch("p1").status == "pushed"


def test_applied_files_accumulate_across_per_file_applies():
    scm.open_branch("p1", "AMS-103", "t")
    scm.record_applied("p1", ["a.py"])
    state = scm.record_applied("p1", ["b.py", "a.py"])
    assert state.staged_files == ["a.py", "b.py"]


def test_commit_refuses_without_a_branch():
    with pytest.raises(scm.ScmError, match="No branch open"):
        scm.commit_branch("nope", "msg")


def test_commit_refuses_an_empty_branch():
    scm.open_branch("p1", "AMS-103", "t")
    with pytest.raises(scm.ScmError, match="Nothing to commit"):
        scm.commit_branch("p1", "msg")


def test_commit_is_idempotent():
    """A double-click must not invent a second commit."""
    scm.open_branch("p1", "AMS-103", "t")
    scm.record_applied("p1", ["a.py"])
    first = scm.commit_branch("p1", "msg")
    second = scm.commit_branch("p1", "a different message")
    assert second.commit == first.commit


def test_commit_sha_is_stable_across_reads():
    """Derived, not random: a transcript that shows a new sha on every reload
    looks like it is inventing history."""
    scm.open_branch("p1", "AMS-103", "t")
    scm.record_applied("p1", ["a.py"])
    sha = scm.commit_branch("p1", "msg").commit.sha
    assert scm.state_for("p1").commit.sha == sha


def test_push_refuses_without_a_commit():
    scm.open_branch("p1", "AMS-103", "t")
    scm.record_applied("p1", ["a.py"])
    with pytest.raises(scm.ScmError, match="Nothing to push"):
        scm.push_branch("p1")


def test_push_is_idempotent():
    scm.open_branch("p1", "AMS-103", "t")
    scm.record_applied("p1", ["a.py"])
    scm.commit_branch("p1", "msg")
    first = scm.push_branch("p1")
    assert scm.push_branch("p1").pushed_at == first.pushed_at


def test_reverting_everything_abandons_the_branch():
    scm.open_branch("p1", "AMS-103", "t")
    scm.record_applied("p1", ["a.py", "b.py"])
    assert scm.record_reverted("p1", ["a.py"]).status == "applied"
    assert scm.record_reverted("p1", ["b.py"]).status == "abandoned"


def test_revert_does_not_rewind_an_existing_commit():
    """In a real repo the commit exists once it is made; the honest undo is an
    abandoned branch or a revert commit, not a rewritten history."""
    scm.open_branch("p1", "AMS-103", "t")
    scm.record_applied("p1", ["a.py"])
    scm.commit_branch("p1", "msg")
    state = scm.record_reverted("p1", ["a.py"])
    assert state.status == "abandoned"
    assert state.commit is not None, "the commit that was made still happened"


def test_reopening_an_abandoned_branch_clears_the_abandonment():
    """Revert, change your mind, apply again."""
    scm.open_branch("p1", "AMS-103", "t")
    scm.record_applied("p1", ["a.py"])
    scm.record_reverted("p1", ["a.py"])
    assert scm.open_branch("p1", "AMS-103", "t").abandoned_at is None


def test_record_applied_without_a_branch_is_a_no_op():
    """A caller applying outside the SCM flow is not forced through it."""
    assert scm.record_applied("never-opened", ["a.py"]) is None


def test_state_survives_a_round_trip_to_disk():
    scm.open_branch("p1", "AMS-103", "t")
    scm.record_applied("p1", ["a.py"])
    scm.commit_branch("p1", "AMS-103: do the thing")
    scm.push_branch("p1")

    reloaded = scm.state_for("p1")
    assert reloaded.branch == "feature/AMS-103-t"
    assert reloaded.commit.message == "AMS-103: do the thing"
    assert reloaded.pipeline_id.startswith("pipeline-")
    assert reloaded.status == "pushed"


def test_state_for_unknown_proposal_is_none():
    assert scm.state_for("never-existed") is None


# --- the commit gate --------------------------------------------------------
#
# Read out of the ticket's event log rather than from a client-supplied boolean:
# a client that could assert "tests passed" could commit a red branch, and the
# beat's whole claim is that the commit happened *because* the tests were green.


def test_gate_blocks_when_the_suite_never_ran():
    assert scm.commit_blockers([]) == [
        "The generated suite has not been run against this change yet — "
        "run the tests before committing."
    ]


def test_gate_blocks_a_failing_generated_suite():
    blockers = scm.commit_blockers([{"action": "tests_failed", "detail": "3/12 passed"}])
    assert len(blockers) == 1
    assert "3/12 passed" in blockers[0]


def test_gate_opens_once_the_suite_passes():
    assert scm.commit_blockers([{"action": "tests_passed", "detail": "12/12 passed"}]) == []


def test_gate_reads_the_latest_run_not_any_run():
    """Failed, fixed, passed reads as passing; passed then broke reads as broken.
    Anything else lets a stale green result gate a red branch."""
    fixed = [
        {"action": "tests_failed", "detail": "3/12 passed"},
        {"action": "tests_passed", "detail": "12/12 passed"},
    ]
    broke = [
        {"action": "tests_passed", "detail": "12/12 passed"},
        {"action": "tests_failed", "detail": "9/12 passed"},
    ]
    assert scm.commit_blockers(fixed) == []
    assert scm.commit_blockers(broke)


def test_gate_blocks_a_failing_regression_suite():
    """The user story broke something that already worked — the one result the whole
    regression beat exists to catch."""
    blockers = scm.commit_blockers(
        [
            {"action": "tests_passed", "detail": "12/12 passed"},
            {"action": "regression_failed", "detail": "13/15 pre-existing tests passed"},
        ]
    )
    assert len(blockers) == 1
    assert "broke something that already worked" in blockers[0]


def test_gate_does_not_block_on_a_regression_suite_that_never_ran():
    """Some targets have no suite; that is a gap in the release record (see
    release.unproven_claims), not a reason the commit cannot happen."""
    assert scm.commit_blockers([{"action": "tests_passed", "detail": "12/12"}]) == []


def test_gate_ignores_unrelated_events():
    events = [
        {"action": "code_change_applied", "detail": "prop-1"},
        {"action": "design_doc_drafted", "detail": ""},
        {"action": "tests_passed", "detail": "12/12 passed"},
    ]
    assert scm.commit_blockers(events) == []


def test_evidence_summary_reports_both_suites():
    summary = scm.evidence_summary(
        [
            {"action": "tests_passed", "detail": "12/12 passed", "ts": "t1"},
            {"action": "regression_passed", "detail": "15/15 passed", "ts": "t2"},
        ]
    )
    assert summary["generated_suite"] == {"passed": True, "detail": "12/12 passed", "ts": "t1"}
    assert summary["regression_suite"]["passed"] is True


def test_evidence_summary_distinguishes_not_run_from_failed():
    """None and passed:False are different claims — the console shows different
    words for them, and conflating the two is how "not run" becomes "green"."""
    summary = scm.evidence_summary([])
    assert summary["generated_suite"] is None
    assert summary["regression_suite"] is None

    failed = scm.evidence_summary([{"action": "regression_failed", "detail": "13/15", "ts": "t"}])
    assert failed["regression_suite"]["passed"] is False


# --- the transcript ---------------------------------------------------------


def test_transcript_grows_with_the_flow():
    """Rendered from state, so it can only ever show steps that happened."""
    scm.open_branch("p1", "AMS-103", "t")
    assert scm.git_transcript(scm.state_for("p1")) == [
        "$ git checkout -b feature/AMS-103-t main"
    ]

    scm.record_applied("p1", ["a.py"])
    assert "$ git add a.py" in scm.git_transcript(scm.state_for("p1"))

    scm.commit_branch("p1", "AMS-103: do the thing")
    transcript = scm.git_transcript(scm.state_for("p1"))
    assert any("git commit -m" in line for line in transcript)
    assert not any("git push" in line for line in transcript), "not pushed yet"

    scm.push_branch("p1")
    assert any("git push origin feature/AMS-103-t" in line for line in scm.git_transcript(
        scm.state_for("p1")
    ))


def test_transcript_shows_the_branch_being_deleted_when_abandoned():
    scm.open_branch("p1", "AMS-103", "t")
    scm.record_applied("p1", ["a.py"])
    scm.record_reverted("p1", ["a.py"])
    transcript = scm.git_transcript(scm.state_for("p1"))
    assert any("git branch -D" in line for line in transcript)


def test_commit_message_is_assembled_not_drafted():
    """Pure string work on data already on hand — no cache key to warm and
    nothing to be confidently wrong about on stage, the same reasoning as
    diagram.py and acceptance.py."""
    assert (
        scm.commit_message_for("AMS-103", "US-2026-043", "claims deductible handling")
        == "AMS-103: claims deductible handling (US-2026-043)"
    )
    assert scm.commit_message_for("AMS-103", "US-2026-043") == "AMS-103: US-2026-043"
    assert scm.commit_message_for("", "") == "apply reviewed AI change"


def test_commit_summary_comes_from_the_target_display_name():
    """The only human description of the change S3 has without asking a model."""
    assert (
        scm.summary_from_display_name(
            "ClaimsPortal — claims deductible handling (US-2026-043)"
        )
        == "claims deductible handling"
    )
    assert (
        scm.summary_from_display_name("MapleSure mockapp — amendment priority field (US-2026-042)")
        == "amendment priority field"
    )


def test_unrecognised_display_name_yields_no_summary():
    """Better an empty summary (the subject falls back to the user story label) than a
    whole display name, app and user story number included, in the subject line."""
    assert scm.summary_from_display_name("Some target with no dash") == ""


def test_real_targets_all_produce_a_readable_commit_subject():
    """Guards the parse against a display name being reworded later — a silent
    fallback here would show `AMS-103: US-2026-043` on stage."""
    from s3_enhancement import targets

    for target in (
        targets.CLAIMSPORTAL_CLAIMS_DEDUCTIBLE,
        targets.MOCKAPP_AMENDMENT_FIELD_ADD,
        targets.MOCKAPP_TIER_UPGRADE,
    ):
        summary = scm.summary_from_display_name(target.display_name)
        assert summary, f"{target.target_id} produced no commit summary"
        assert "US-" not in summary, f"{target.target_id} leaked the story id into the summary"
        assert "(" not in summary and ")" not in summary
