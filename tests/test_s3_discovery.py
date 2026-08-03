"""Target auto-discovery from the `repos/` drop folder.

The onboarding claim S3 makes on stage is "drop the repo in and add its user stories".
These tests are what stop that from quietly becoming false: they exercise the
manifest contract end to end against a real directory, not a mocked one.
"""

from __future__ import annotations

import json

import pytest

from s3_enhancement import discovery


def _write_manifest(repos_dir, name: str, payload) -> None:
    repo = repos_dir / name
    repo.mkdir(parents=True, exist_ok=True)
    (repo / discovery.MANIFEST_NAME).write_text(json.dumps(payload), encoding="utf-8")


@pytest.fixture
def repos_dir(tmp_path, monkeypatch):
    """Point discovery at a throwaway repos/ so these never depend on — or
    disturb — the three real targets."""
    target = tmp_path / "repos"
    target.mkdir()
    monkeypatch.setattr(discovery, "REPOS_DIR", target)
    monkeypatch.setattr(discovery, "REPO_ROOT", tmp_path)
    return target


MINIMAL = {
    "target_id": "acme-widget",
    "cache_namespace": "acme_widget",
    "codegen_allowlist": ["repos/acme/widget.py"],
}


def test_a_repo_without_a_manifest_is_ignored(repos_dir):
    """Source dropped in before its manifest must not half-register."""
    (repos_dir / "acme").mkdir()
    assert discovery.discover_manifest_targets() == []


def test_a_manifest_registers_its_target(repos_dir):
    _write_manifest(repos_dir, "acme", {"targets": [MINIMAL]})
    found = discovery.discover_manifest_targets()
    assert [t.target_id for t in found] == ["acme-widget"]
    assert found[0].root == repos_dir / "acme"
    assert found[0].codegen_allowlist == ("repos/acme/widget.py",)


def test_one_repo_may_declare_several_targets(repos_dir):
    """PolicyCore has two, one per user story — the shape must generalise."""
    second = {**MINIMAL, "target_id": "acme-gadget", "cache_namespace": "acme_gadget"}
    _write_manifest(repos_dir, "acme", {"targets": [MINIMAL, second]})
    assert len(discovery.discover_manifest_targets()) == 2


def test_discovery_order_is_deterministic(repos_dir):
    """Sorted, not filesystem order — so a collision error is reproducible."""
    _write_manifest(repos_dir, "zeta", {"targets": [MINIMAL]})
    _write_manifest(
        repos_dir, "alpha",
        {"targets": [{**MINIMAL, "target_id": "a-1", "cache_namespace": "a_1"}]},
    )
    assert [t.target_id for t in discovery.discover_manifest_targets()] == [
        "a-1",
        "acme-widget",
    ]


# --- A broken manifest must fail loudly, never silently ---------------------


def test_missing_target_id_raises(repos_dir):
    _write_manifest(repos_dir, "acme", {"targets": [{"cache_namespace": "x"}]})
    with pytest.raises(discovery.ManifestError, match="target_id"):
        discovery.discover_manifest_targets()


def test_missing_cache_namespace_raises(repos_dir):
    """Empty is reserved for the legacy default target; a discovered target
    taking it would collide on every single cache key."""
    _write_manifest(repos_dir, "acme", {"targets": [{"target_id": "acme-widget"}]})
    with pytest.raises(discovery.ManifestError, match="cache_namespace"):
        discovery.discover_manifest_targets()


def test_invalid_json_raises(repos_dir):
    repo = repos_dir / "acme"
    repo.mkdir()
    (repo / discovery.MANIFEST_NAME).write_text("{ not json", encoding="utf-8")
    with pytest.raises(discovery.ManifestError, match="invalid JSON"):
        discovery.discover_manifest_targets()


def test_missing_targets_list_raises(repos_dir):
    _write_manifest(repos_dir, "acme", {"target": MINIMAL})
    with pytest.raises(discovery.ManifestError, match="targets"):
        discovery.discover_manifest_targets()


def test_a_story_path_that_does_not_exist_raises(repos_dir):
    """Catches the typo at import rather than at Step 0 in front of an audience."""
    _write_manifest(repos_dir, "acme", {"targets": [{**MINIMAL, "story": "stories/nope.md"}]})
    with pytest.raises(discovery.ManifestError, match="does not exist"):
        discovery.discover_manifest_targets()


def test_a_string_where_a_list_belongs_raises(repos_dir):
    """`"core_files": "a.py"` would otherwise silently become one char per entry."""
    _write_manifest(repos_dir, "acme", {"targets": [{**MINIMAL, "core_files": "a.py"}]})
    with pytest.raises(discovery.ManifestError, match="must be a list"):
        discovery.discover_manifest_targets()


# --- Registration -----------------------------------------------------------


def test_built_in_targets_win_on_an_id_clash(repos_dir):
    """A built-in carries a bespoke codegen validator a manifest cannot
    express, so a manifest re-declaring its id is skipped, not honoured."""
    _write_manifest(repos_dir, "acme", {"targets": [MINIMAL]})
    registry = {"acme-widget": object()}
    registered = discovery.register_discovered(
        lambda t: pytest.fail("must not register over a built-in"), registry
    )
    assert registered == []


def test_a_new_target_is_registered(repos_dir):
    _write_manifest(repos_dir, "acme", {"targets": [MINIMAL]})
    seen = []
    assert discovery.register_discovered(seen.append, {}) == ["acme-widget"]
    assert [t.target_id for t in seen] == ["acme-widget"]


def test_mutations_are_parsed_into_mutation_objects(repos_dir):
    """`old_snippet` quotes generated code verbatim — it has to survive the
    manifest round-trip byte-for-byte or the seeded-bug beat mutates nothing."""
    _write_manifest(
        repos_dir, "acme",
        {"targets": [{**MINIMAL, "mutations": [
            {"rel_path": "repos/acme/widget.py",
             "old_snippet": "if amount <= limit:",
             "new_snippet": "if amount < limit:",
             "description": "Weakened the boundary check."}]}]},
    )
    mutation = discovery.discover_manifest_targets()[0].mutations[0]
    assert mutation.old_snippet == "if amount <= limit:"
    assert mutation.rel_path == "repos/acme/widget.py"
