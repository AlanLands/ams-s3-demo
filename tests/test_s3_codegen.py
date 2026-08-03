"""Unit tests for s3_enhancement.codegen's filesystem-only helpers: per-file
apply and adding an extra file to an in-review proposal. Both operate purely
on staged/repo paths, so they're tested against a throwaway REPO_ROOT/OUT_ROOT
rather than an LLM call.
"""

from __future__ import annotations

import pytest

from s3_enhancement import codegen
from s3_enhancement.codegen import LLMError


@pytest.fixture
def staged_proposal(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    out_root = repo_root / "s3_enhancement" / "out"
    monkeypatch.setattr(codegen, "REPO_ROOT", repo_root)
    monkeypatch.setattr(codegen, "OUT_ROOT", out_root)

    staged_dir = out_root / "prop-1" / "staged"
    (staged_dir / "pkg").mkdir(parents=True)
    (staged_dir / "pkg" / "a.py").write_text("A = 1\n")
    (staged_dir / "b.py").write_text("B = 2\n")
    return repo_root, staged_dir


def test_apply_change_all_files(staged_proposal):
    repo_root, _staged_dir = staged_proposal
    applied = codegen.apply_change("prop-1")
    assert applied == ["b.py", "pkg/a.py"]
    assert (repo_root / "b.py").read_text() == "B = 2\n"
    assert (repo_root / "pkg" / "a.py").read_text() == "A = 1\n"


def test_apply_change_single_file(staged_proposal):
    repo_root, _staged_dir = staged_proposal
    applied = codegen.apply_change("prop-1", file_path="b.py")
    assert applied == ["b.py"]
    assert (repo_root / "b.py").read_text() == "B = 2\n"
    assert not (repo_root / "pkg" / "a.py").exists()


def test_apply_change_unknown_file_raises(staged_proposal):
    with pytest.raises(LLMError, match="not part of staged proposal"):
        codegen.apply_change("prop-1", file_path="nope.py")


def test_apply_change_unknown_proposal_raises(staged_proposal):
    with pytest.raises(LLMError, match="No staged proposal found"):
        codegen.apply_change("does-not-exist")


def test_drop_unchanged_files_keeps_only_real_changes(monkeypatch, tmp_path):
    """A proposal should never stage a file the model returned byte-identical
    to the repo (or one an earlier run already applied) — only actual pending
    changes reach the review cards. A file the repo doesn't have yet (the user story
    creates it) always counts as changed, even when returned empty."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    monkeypatch.setattr(codegen, "REPO_ROOT", repo_root)
    (repo_root / "same.py").write_text("A = 1\n")
    (repo_root / "edited.py").write_text("B = 2\n")

    files = {
        "same.py": "A = 1\n",  # identical -> dropped
        "edited.py": "B = 3\n",  # real change -> kept
        "brand_new.py": "C = 4\n",  # repo doesn't have it -> kept
        "new_empty.py": "",  # created empty is still a creation -> kept
    }
    assert codegen._drop_unchanged_files(files) == {
        "edited.py": "B = 3\n",
        "brand_new.py": "C = 4\n",
        "new_empty.py": "",
    }


def test_stage_files_creates_dir_even_with_no_files(monkeypatch, tmp_path):
    """An all-unchanged proposal stages zero files but must still be
    addressable by proposal_id — apply becomes a no-op, not a 502."""
    monkeypatch.setattr(codegen, "OUT_ROOT", tmp_path / "out")
    staged_dir = codegen._stage_files({})
    assert staged_dir.is_dir()
    assert codegen.apply_change(staged_dir.parent.name) == []


def test_safe_repo_relative_path_rejects_absolute():
    with pytest.raises(LLMError, match="not.*absolute"):
        codegen._safe_repo_relative_path("/etc/passwd")


def test_safe_repo_relative_path_rejects_traversal(monkeypatch, tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    monkeypatch.setattr(codegen, "REPO_ROOT", repo_root)
    with pytest.raises(LLMError, match="outside the repo"):
        codegen._safe_repo_relative_path("../secrets.txt")


def test_add_file_to_proposal_bootstraps_new_file_and_revises(staged_proposal, monkeypatch):
    repo_root, staged_dir = staged_proposal
    (repo_root / "c.py").write_text("C = 3\n")

    def fake_revise(proposal_id, instruction, *, target=None):
        assert proposal_id == "prop-1"
        assert instruction == "For c.py: bump C to 4"
        assert (staged_dir / "c.py").read_text() == "C = 3\n"
        return codegen.CodegenResult(
            tier_name="",
            diff_text="diff",
            files_changed=["c.py"],
            used_replay=False,
            stream_text_generator=None,
            proposal_id=proposal_id,
        )

    monkeypatch.setattr(codegen, "revise_change", fake_revise)
    result = codegen.add_file_to_proposal("prop-1", "c.py", "bump C to 4")
    assert result.files_changed == ["c.py"]


def test_add_file_to_proposal_missing_source_raises(staged_proposal):
    with pytest.raises(LLMError, match="does not exist in the repo"):
        codegen.add_file_to_proposal("prop-1", "missing.py", "do something")


def test_add_file_to_proposal_already_staged_skips_bootstrap(staged_proposal, monkeypatch):
    """A file already part of the proposal (e.g. the AI's own selection)
    shouldn't be overwritten with the on-repo copy before revising it."""
    _repo_root, staged_dir = staged_proposal

    def fake_revise(proposal_id, instruction, *, target=None):
        assert (staged_dir / "b.py").read_text() == "B = 2\n"
        return codegen.CodegenResult(
            tier_name="",
            diff_text="diff",
            files_changed=["b.py"],
            used_replay=False,
            stream_text_generator=None,
            proposal_id=proposal_id,
        )

    monkeypatch.setattr(codegen, "revise_change", fake_revise)
    codegen.add_file_to_proposal("prop-1", "b.py", "tweak it")
