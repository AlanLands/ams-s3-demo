"""Verifies s3_enhancement/diagram.py (the derived change map) and
s3_enhancement/designdoc.py (the standalone HTML/PDF document)."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from s3_enhancement import diagram, targets
from s3_enhancement.designdoc import (
    PdfUnavailableError,
    parse_doc_blocks,
    render_document_html,
    render_pdf,
)
from s3_enhancement.diagram import (
    build_change_map,
    build_svg,
    caption_for,
    render_svg,
)

SPRING = targets.CLAIMSPORTAL_CLAIMS_DEDUCTIBLE
POLICYCORE = targets.MOCKAPP_AMENDMENT_FIELD_ADD


def test_layers_files_by_convention():
    change_map = build_change_map(POLICYCORE)
    by_name = {node.filename: node.layer for node in change_map.nodes}
    assert by_name["app.py"] == "Interface"
    assert by_name["amendments.py"] == "Logic"
    assert by_name["db.py"] == "Data"
    assert by_name["models.py"] == "Data"


def test_python_records_land_in_the_data_layer():
    """policy.py and claim.py are field-only pydantic models with no suffix
    that says "data" — without the explicit list they would fall through to
    Logic."""
    change_map = build_change_map(SPRING)
    by_path = {node.rel_path: node.layer for node in change_map.nodes}
    assert by_path["repos/claimsportal/policy_service/policy.py"] == "Data"
    assert by_path["repos/claimsportal/claims_service/claim.py"] == "Data"
    assert by_path["repos/claimsportal/claims_service/main.py"] == "Interface"
    assert by_path["repos/claimsportal/claims_service/claim_rules.py"] == "Logic"


def test_single_service_target_is_one_column():
    assert build_change_map(POLICYCORE).services == ["policycore"]


def test_two_service_target_splits_by_python_package():
    """repos/claimsportal is one target root holding two deployables; the
    diagram has to show them apart or the change looks like one service."""
    assert set(build_change_map(SPRING).services) == {"claims_service", "policy_service"}


def test_cross_service_call_points_from_caller_to_callee():
    """policy_client.py in claims_service calls policy_service. Drawn
    backwards it would tell QA to test the dependency the wrong way round."""
    assert build_change_map(SPRING).crossings == [("claims_service", "policy_service")]


def test_no_crossing_claimed_for_a_single_service():
    assert build_change_map(POLICYCORE).crossings == []


def test_new_files_are_badged_and_existing_ones_are_not():
    """claim_rules.py does not exist until CR-2026-043 creates it. Fakes git
    so the assertion doesn't depend on whether this checkout has committed
    the rewritten target's baseline files yet."""

    def fake_run(cmd, **kwargs):
        rel_path = cmd[-1].split(":", 1)[1]
        return SimpleNamespace(returncode=1 if rel_path.endswith("claim_rules.py") else 0)

    with patch.object(diagram.subprocess, "run", side_effect=fake_run):
        change_map = build_change_map(SPRING)
    by_path = {node.rel_path: node.is_new for node in change_map.nodes}
    assert by_path["repos/claimsportal/claims_service/claim_rules.py"] is True
    assert by_path["repos/claimsportal/claims_service/main.py"] is False


def test_new_file_detection_degrades_to_modified_without_git():
    """An unbadged box is a smaller error than a wrong badge."""
    with patch.object(diagram.subprocess, "run", side_effect=OSError("no git")):
        assert diagram._is_new("repos/policycore/app.py") is False


def test_svg_is_self_contained():
    """It has to render inside the console, inside an exported HTML file, and
    in a print-to-PDF — so it may not reference anything external."""
    svg, _ = build_svg(SPRING)
    assert svg.startswith("<svg") and svg.endswith("</svg>")
    # The SVG namespace URI is a required identifier, not a fetch; everything
    # else that looks like a URL would be.
    body = svg.replace('xmlns="http://www.w3.org/2000/svg"', "")
    for forbidden in ("<script", "http://", "https://", "@import", "<link", "<image"):
        assert forbidden not in body


def test_svg_names_every_changed_file():
    svg, change_map = build_svg(SPRING)
    for node in change_map.nodes:
        assert node.filename in svg


def test_svg_escapes_downstream_names():
    svg, _ = build_svg(POLICYCORE, downstream=["<script>alert(1)</script>"])
    assert "<script>" not in svg
    assert "&lt;script&gt;" in svg


def test_empty_change_set_renders_a_placeholder_not_a_crash():
    change_map = build_change_map(POLICYCORE, changed_files=[])
    svg = render_svg(change_map)
    assert "No changed files to map" in svg


def test_downstream_apps_appear_only_when_supplied():
    plain, _ = build_svg(POLICYCORE)
    assert "DOWNSTREAM" not in plain
    with_apps, _ = build_svg(POLICYCORE, downstream=["BillingGateway"])
    assert "DOWNSTREAM" in with_apps and "BillingGateway" in with_apps


# --- the document -----------------------------------------------------------

SAMPLE_DOC = """1. Summary
Adds a priority field.

2. Risk areas
- **Backward compatibility**: existing submissions must still work.
- Schema migration on the amendments table.
"""


def test_parses_the_shapes_the_model_actually_emits():
    kinds = [block.kind for block in parse_doc_blocks(SAMPLE_DOC)]
    assert kinds == ["heading", "paragraph", "heading", "bullet", "bullet"]


def test_document_html_carries_letterhead_and_metadata():
    html = render_document_html(
        SAMPLE_DOC, cr_label="CR-2026-042", ticket_key="AMS-102", today=date(2026, 7, 29)
    )
    assert "MapleSure Insurance" in html
    assert "CR-2026-042" in html and "AMS-102" in html
    assert "29 July 2026" in html
    assert "<strong>Backward compatibility</strong>" in html


def test_document_html_embeds_the_diagram_with_its_provenance():
    """The caption is not decoration: without it a reader assumes the model
    drew the diagram, which is the one thing it did not do."""
    svg, change_map = build_svg(POLICYCORE)
    html = render_document_html(
        SAMPLE_DOC,
        cr_label="CR",
        ticket_key="AMS-102",
        diagram_svg=svg,
        diagram_caption=caption_for(change_map),
    )
    assert "<figure>" in html and "<svg" in html
    assert "not generated by a model" in html


def test_caption_only_claims_what_the_diagram_shows():
    """A single-service change has no cross-service call, and a caption that
    mentions one is the kind of small inaccuracy that costs credibility."""
    single = caption_for(build_change_map(POLICYCORE))
    assert "cross-service call" not in single
    assert "services" not in single

    multi = caption_for(build_change_map(SPRING))
    assert "services, layers and the cross-service call" in multi


def test_document_html_omits_the_figure_when_no_diagram_is_given():
    html = render_document_html(SAMPLE_DOC, cr_label="CR", ticket_key="AMS-102")
    assert "<figure>" not in html


def test_document_html_escapes_the_model_text():
    html = render_document_html(
        "<script>alert(1)</script>", cr_label="CR", ticket_key="AMS-102"
    )
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_render_pdf_reports_a_missing_browser_as_unavailable():
    """A locked-down machine can have the Playwright package without the
    browser binary; that must degrade, not 500."""
    from playwright.sync_api import Error as PlaywrightError

    with patch(
        "playwright.sync_api.sync_playwright", side_effect=PlaywrightError("no chromium")
    ):
        with pytest.raises(PdfUnavailableError, match="Chromium is not installed"):
            render_pdf("<html><body>x</body></html>")
