"""Templated change request driving the S3 Enhancement Delivery demo beat.

The audience chooses the top plan tier name at runtime. The baseline repo
therefore stores the CR with a literal placeholder and renders it only inside
the S3 console flow.
"""

from __future__ import annotations

from common.constants import INSURER_NAME
from s3_enhancement import targets
from s3_enhancement.targets import Target

CR_TEMPLATE_PATH = targets.MOCKAPP_TIER_UPGRADE.cr_template_path
PLACEHOLDER = targets.MOCKAPP_TIER_UPGRADE.cr_placeholder

_BAD_INPUT_CHARS = ('"', "'", "/", "\\")


def sanitize_tier_name(raw: str) -> tuple[str | None, str | None]:
    """Validate an audience-picked tier name. Returns (tier_name, error_message)."""
    tier_name = raw.strip()
    if not tier_name:
        return None, "Enter a plan tier name."
    if len(tier_name) > 24:
        return None, "Keep the tier name to 24 characters or fewer."
    if any(char in tier_name for char in _BAD_INPUT_CHARS):
        return None, "Use a plain display name without quotes or path separators."
    lowered = tier_name.lower()
    if lowered == INSURER_NAME.lower() or "client" in lowered or "tcs" in lowered:
        return None, "Use a synthetic tier name only."
    return tier_name, None


def render_cr(tier_name: str, *, target: Target | None = None) -> str:
    """tier_name must already be sanitized by the caller (see sanitize_tier_name).

    Targets with no audience-picked placeholder (`cr_placeholder == ""`) render
    their CR text unchanged — `str.replace("", ...)` would otherwise insert
    `tier_name` between every character, so the empty-placeholder case is a
    deliberate no-op, not an oversight.
    """
    target = target or targets.get_target(None)
    text = target.cr_template_path.read_text(encoding="utf-8")
    if not target.cr_placeholder:
        return text
    return text.replace(target.cr_placeholder, tier_name)


def raw_cr_template(*, target: Target | None = None) -> str:
    """Return the CR with the literal placeholder still in it.

    Used only when recording a replay cache entry, so generated files also
    contain the placeholder token verbatim for later substitution.
    """
    target = target or targets.get_target(None)
    return target.cr_template_path.read_text(encoding="utf-8")
