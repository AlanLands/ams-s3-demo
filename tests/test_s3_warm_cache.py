from unittest.mock import patch

from s3_enhancement import targets
from s3_enhancement.warm_cache import warm


def test_warm_covers_every_registered_target():
    """Regression test for the cold-cache design-doc failure: warm() must warm
    draft_design_doc (and the other narrative beats) for every registered
    target, not just the default one. Before this fix, non-default targets'
    design docs were never pre-cached, so the first live click after a reset
    was a guaranteed cold call."""
    with (
        patch("s3_enhancement.warm_cache.draft_effort_estimate") as mock_effort,
        patch("s3_enhancement.warm_cache.draft_impact_analysis") as mock_impact,
        patch("s3_enhancement.warm_cache.draft_design_doc") as mock_design_doc,
        patch("s3_enhancement.warm_cache.draft_release_notes") as mock_release_notes,
    ):
        warm()

    warmable_ids = {t.target_id for t in targets.all_targets() if t.cr_template_path is not None}
    assert {
        targets.DEFAULT_TARGET_ID,
        targets.ENDORSEMENT_TARGET_ID,
        targets.CLAIMSPORTAL_TARGET_ID,
    } <= warmable_ids

    for mock in (mock_effort, mock_impact, mock_design_doc, mock_release_notes):
        assert mock.call_count == len(warmable_ids)
        warmed_target_ids = {call.kwargs["target"].target_id for call in mock.call_args_list}
        assert warmed_target_ids == warmable_ids
