"""Tests for s3_enhancement/targets.py's collision-prevention and per-target
discovery — the seam that lets S3 scale from one repo/CR to many without
different targets silently sharing cached LLM output."""

from __future__ import annotations

import pytest

from s3_enhancement import relevance, targets
from s3_enhancement.targets import Target


def test_default_target_cache_keys_match_legacy_literals():
    """The one property this whole abstraction must never break: the default
    target's cache identity is byte-identical to the pre-refactor literals, so
    the committed replay recordings (s3_codegen.json, s3_testgen.json) and
    .cache/llm's existing entries need no re-recording."""
    default = targets.get_target(None)
    assert default.stream_cache_key("codegen") == "s3_codegen"
    assert default.stream_cache_key("testgen") == "s3_testgen"
    assert default.cache_key("impact_analysis") == "s3_impact_analysis:coverage_upgrade:v2"
    assert default.cache_key("effort_estimate") == "s3_effort_estimate:coverage_upgrade:v2"
    assert default.cache_key("release_notes") == "s3_release_notes:coverage_upgrade"


def test_get_target_defaults_to_mockapp_coverage_upgrade():
    assert targets.get_target(None) is targets.MOCKAPP_COVERAGE_UPGRADE
    assert targets.get_target(targets.DEFAULT_TARGET_ID) is targets.MOCKAPP_COVERAGE_UPGRADE


def test_second_target_has_distinct_cache_identity(tmp_path):
    second = Target(
        target_id="synthetic-second-repo",
        source_kind="local",
        display_name="synthetic second repo (test-only)",
        root=tmp_path,
        core_files=("app.py",),
        cache_namespace="synthetic-second-repo",
    )
    default = targets.get_target(None)

    assert second.stream_cache_key("codegen") != default.stream_cache_key("codegen")
    assert second.cache_key("impact_analysis") != default.cache_key("impact_analysis")
    assert second.stream_cache_key("codegen") == "s3_codegen__synthetic-second-repo"
    assert second.cache_key("impact_analysis") == (
        "s3_impact_analysis:synthetic-second-repo:v1"
    )


def test_register_target_rejects_duplicate_target_id():
    with pytest.raises(ValueError, match="already registered"):
        targets.register_target(
            Target(
                target_id=targets.DEFAULT_TARGET_ID,
                source_kind="local",
                display_name="duplicate id",
                cache_namespace="some-other-namespace",
            )
        )


def test_register_target_rejects_duplicate_cache_namespace():
    namespace = "duplicate-namespace-test"
    targets.register_target(
        Target(
            target_id="dup-namespace-a",
            source_kind="local",
            display_name="first",
            cache_namespace=namespace,
        )
    )
    with pytest.raises(ValueError, match="already used by"):
        targets.register_target(
            Target(
                target_id="dup-namespace-b",
                source_kind="local",
                display_name="second",
                cache_namespace=namespace,
            )
        )


def test_discover_files_for_target_scopes_to_local_target_root(tmp_path):
    (tmp_path / "app.py").write_text("print('hello from synthetic repo')\n")
    (tmp_path / "helper.py").write_text("def helper():\n    pass\n")

    second = Target(
        target_id="synthetic-discovery-target",
        source_kind="local",
        display_name="synthetic discovery target (test-only)",
        root=tmp_path,
        core_files=("app.py",),
        cache_namespace="synthetic-discovery-target",
    )

    files = relevance.discover_files_for_target(second, cr_text="add a feature")

    assert set(files) == {"app.py", "helper.py"}
    assert "hello from synthetic repo" in files["app.py"]
    # Proves scoping to the target's own root, not mockapp/.
    assert "mockapp/core/models.py" not in files
