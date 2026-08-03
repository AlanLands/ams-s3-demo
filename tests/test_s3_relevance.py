"""Tests for s3_enhancement/relevance.py's scoped file-selection logic.

Runs against the real repos/policycore/ tree (including the repos/policycore/systems/ decoy
padding), not a fixture — the whole point of this module is to prove
selection behaves correctly at the actual demo-day scale.
"""

from __future__ import annotations

import pytest

from s3_enhancement import cr, relevance, targets


def test_discover_mockapp_files_returns_the_full_candidate_pool() -> None:
    files = relevance.discover_mockapp_files()
    assert 45 <= len(files) <= 60
    assert any(path.endswith(".java") for path in files)
    assert any(path.endswith(".py") for path in files)


def test_canonical_cr_selects_only_core_files() -> None:
    cr_text = cr.render_cr("Elite")
    all_files = relevance.discover_mockapp_files()
    selection = relevance.select_relevant_files(cr_text, all_files)

    assert set(selection.selected) == set(relevance.CORE_FILES)
    assert selection.extra_files == ()
    for decoy_path in selection.selected:
        assert "repos/policycore/systems/" not in decoy_path


def test_canonical_cr_selection_is_deterministic_across_runs() -> None:
    cr_text = cr.render_cr("Elite")
    all_files = relevance.discover_mockapp_files()
    first = relevance.select_relevant_files(cr_text, all_files)
    second = relevance.select_relevant_files(cr_text, all_files)
    third = relevance.select_relevant_files(cr_text, all_files)

    assert set(first.selected) == set(second.selected) == set(third.selected)
    assert first.extra_files == second.extra_files == third.extra_files


def test_core_files_included_even_when_missing_on_disk() -> None:
    all_files = {"repos/policycore/core/models.py": "class Policy: ...", "repos/policycore/systems/x.py": "x = 1"}
    selection = relevance.select_relevant_files("some CR text", all_files)

    assert selection.selected["repos/policycore/core/tiers.py"] == ""
    assert selection.selected["repos/policycore/core/models.py"] == "class Policy: ..."


def test_verify_core_recall_passes_on_a_full_selection() -> None:
    cr_text = cr.render_cr("Elite")
    all_files = relevance.discover_mockapp_files()
    selection = relevance.select_relevant_files(cr_text, all_files)
    relevance.verify_core_recall(selection.selected)


def test_verify_core_recall_raises_on_incomplete_file_set() -> None:
    incomplete = {"repos/policycore/core/models.py": "...", "repos/policycore/core/db.py": "..."}
    with pytest.raises(Exception, match="missing required core file"):
        relevance.verify_core_recall(incomplete)


def test_candidate_pool_by_language_counts_both_languages() -> None:
    all_files = relevance.discover_mockapp_files()
    selection = relevance.select_relevant_files(cr.render_cr("Elite"), all_files)
    by_language = selection.candidate_pool_by_language
    assert by_language["python"] > 0
    assert by_language["java"] > 0
    assert by_language["python"] + by_language["java"] == selection.candidate_pool_size


def test_estimate_tokens_is_a_rough_positive_heuristic() -> None:
    assert relevance.estimate_tokens("") == 1
    assert relevance.estimate_tokens("a" * 400) == 100


def test_naive_prompt_tokens_adds_the_unselected_files_to_what_was_spent() -> None:
    """The naive prompt is the scoped prompt with every file pasted in, so it
    differs by exactly the unselected files — the shared scaffold (system
    prompt, CR text, instructions) counts on both sides."""
    all_files = {"a.py": "x" * 400, "b.py": "y" * 800}
    naive = relevance.naive_prompt_tokens(1000, all_files, {"a.py": all_files["a.py"]})
    assert naive == 1000 + 200


def test_naive_prompt_tokens_never_undercuts_what_was_actually_spent() -> None:
    """When scoping selects every file there is no saving to claim. Summing
    file bodies alone (the earlier approach) reported a *smaller* number than
    the real prompt, because it dropped the scaffold from the naive side —
    that's what made the ClaimsPortal target's 8-of-8 selection read as though
    whole-app context would have been cheaper."""
    all_files = {"a.py": "x" * 400}
    assert relevance.naive_prompt_tokens(1000, all_files, all_files) == 1000


def test_naive_prompt_tokens_falls_back_when_usage_is_unknown() -> None:
    """A replay recording with no usage has no scoped baseline to build on."""
    all_files = {"a.py": "x" * 400, "b.py": "y" * 800}
    assert relevance.naive_prompt_tokens(None, all_files, {"a.py": all_files["a.py"]}) == 300


def test_discover_subsystem_design_docs_finds_all_legacy_subsystems() -> None:
    docs = relevance.discover_subsystem_design_docs()
    legacy = {name for name in docs if name.startswith("repos/policycore/systems/")}
    assert len(legacy) == 6

    # Not every design-doc-bearing directory is a decoy any more. PolicyCore's
    # own subsystems carry one too, which is the point: the screen then has to
    # reject a same-language, same-shape part of the live app on its domain
    # rather than waving through anything that is not Java.
    assert docs.keys() - legacy == {"repos/policycore/enrolment"}


def test_canonical_cr_screens_out_every_legacy_subsystem() -> None:
    cr_text = cr.render_cr("Elite")
    docs = relevance.discover_subsystem_design_docs()
    screen = relevance.screen_subsystems(cr_text, docs)

    assert screen.in_scope == ()
    assert len(screen.screened_out) == len(docs)


def test_design_docs_are_scoped_to_the_root_they_are_asked_for() -> None:
    """A root with no DESIGN.md yields no docs — not mockapp's.

    `discover_subsystem_design_docs` used to glob `repos/policycore/` unconditionally,
    so any target rooted elsewhere was screened against mockapp's decoy
    subsystems.
    """
    spring_root = targets.CLAIMSPORTAL_CLAIMS_DEDUCTIBLE.root
    assert spring_root is not None
    assert relevance.discover_subsystem_design_docs(spring_root) == {}


def test_non_mockapp_target_is_never_screened_against_mockapp_subsystems() -> None:
    """The UI's "which part of the repo the AI matched this change to" panel
    reads straight off this screen, so a mockapp subsystem showing up as
    in-scope for the ClaimsPortal target is a wrong answer on stage, not cosmetic.
    """
    target = targets.CLAIMSPORTAL_CLAIMS_DEDUCTIBLE
    cr_text = cr.render_cr("Elite", target=target)
    all_files = relevance.discover_files_for_target(target, cr_text)
    selection = relevance.select_relevant_files(
        cr_text, all_files, core_files=target.core_files, design_doc_root=target.root
    )

    screen = selection.subsystem_screen
    assert screen.in_scope == ()
    assert screen.screened_out == ()
    assert screen.scores == {}
    assert all(path.startswith("repos/claimsportal/") for path in selection.selected)


def test_select_relevant_files_never_opens_a_screened_out_subsystems_files() -> None:
    cr_text = cr.render_cr("Elite")
    all_files = relevance.discover_mockapp_files()
    selection = relevance.select_relevant_files(cr_text, all_files)

    assert selection.subsystem_screen.in_scope == ()
    assert set(selection.subsystem_screen.screened_out) == set(
        relevance.discover_subsystem_design_docs()
    )
    for decoy_path in selection.scores:
        assert "repos/policycore/systems/" not in decoy_path


def test_screen_subsystems_with_no_design_docs_screens_nothing() -> None:
    screen = relevance.screen_subsystems("some CR text", {})
    assert screen.in_scope == ()
    assert screen.screened_out == ()
    assert screen.scores == {}
