from unittest.mock import patch

from s3_enhancement import targets
from s3_enhancement.warm_cache import warm


def test_warm_covers_every_registered_target():
    """Regression test for the cold-cache design-doc failure: warm() must warm
    draft_design_doc (and the other narrative beats) for every registered
    target, not just the default one. Before this fix, non-default targets'
    design docs were never pre-cached, so the first live click after a reset
    was a guaranteed cold call."""
    # Every outbound call warm() makes is patched, not just the four this
    # test asserts on. warm()'s whole job is to make live calls, so any beat
    # left unpatched here is a real, billed API call the moment .cache/llm is
    # cold -- which is exactly the state `demo/reset_s3.sh` leaves behind.
    with (
        patch("s3_enhancement.warm_cache.draft_effort_estimate") as mock_effort,
        patch("s3_enhancement.warm_cache.draft_impact_analysis") as mock_impact,
        patch("s3_enhancement.warm_cache.draft_design_doc") as mock_design_doc,
        patch("s3_enhancement.warm_cache.draft_release_notes") as mock_release_notes,
        patch("s3_enhancement.warm_cache.draft_release_note_set"),
        patch("s3_enhancement.warm_cache.draft_scenarios"),
        patch("s3_enhancement.warm_cache.resolve_target_for_story") as mock_resolve,
    ):
        warm()

    warmable_ids = {t.target_id for t in targets.all_targets() if t.story_template_path is not None}
    assert {
        targets.DEFAULT_TARGET_ID,
        targets.AMENDMENT_TARGET_ID,
        targets.CLAIMSPORTAL_TARGET_ID,
    } <= warmable_ids

    for mock in (mock_effort, mock_impact, mock_design_doc, mock_release_notes):
        assert mock.call_count == len(warmable_ids)
        warmed_target_ids = {call.kwargs["target"].target_id for call in mock.call_args_list}
        assert warmed_target_ids == warmable_ids

    # Target resolution is warmed for every user story under stories/, not just the ones
    # that back a registered target. The one that resolves through the AI
    # tier is precisely the user story that names no target, so it has no target to
    # be reached by the loop above -- and its entry lives in .cache/llm,
    # which every reset wipes. Left cold it fails quietly: _match_by_ai turns
    # an LLMError into an "unresolved" match, which the console shows as
    # "couldn't identify the repo" rather than an error.
    stories = sorted(p.name for p in (targets.REPO_ROOT / "stories").glob("*.md"))
    assert stories, "no user stories found to warm resolution for"
    assert mock_resolve.call_count == len(stories)
