"""Before/after screenshot capture for the S3 endorsement-form demo beat
(CR-2026-042) — proves "the app changed" visually, not just via a text diff.

`SCREENSHOT_MODE` mirrors `GITLAB_MODE`/`HARNESS_MODE`/`LLM_MODE`: "live"
launches a real headless browser against the running mockapp instance and
returns the PNG without saving it; "record" does the same and also saves the
PNG so later runs can replay it; "replay" (the demo-day default) just serves
a previously recorded PNG with zero browser/network dependency.

Callers are expected to capture "before" prior to
`s3_enhancement.codegen.apply_change()` and "after" once it has actually run
— screenshotting a merely-proposed (not yet applied) change would show stale
"before" content, defeating the point.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

Stage = Literal["before", "after"]

REPO_ROOT = Path(__file__).resolve().parents[1]
_CACHE_ROOT = REPO_ROOT / "s3_enhancement" / "cache" / "screenshots"
_DEFAULT_MOCKAPP_URL = "http://localhost:8501"
_TIMEOUT_MS = 10_000


class ScreenshotError(Exception):
    """Raised for any screenshot-capture failure or misconfiguration."""


def _screenshot_mode() -> str:
    mode = os.environ.get("SCREENSHOT_MODE", "replay").lower()
    if mode not in {"live", "record", "replay"}:
        raise ScreenshotError(
            f"Unknown SCREENSHOT_MODE {mode!r}; expected 'live', 'record', or 'replay'"
        )
    return mode


def _cache_path(namespace: str, stage: Stage) -> Path:
    return _CACHE_ROOT / f"{namespace}_{stage}.png"


def has_recording(namespace: str, stage: Stage) -> bool:
    return _cache_path(namespace, stage).exists()


def capture_form_screenshot(stage: Stage, *, namespace: str) -> bytes:
    """Capture (or replay) a full-page PNG screenshot of the running mockapp.

    `namespace` mirrors a `Target.cache_namespace` (e.g.
    "endorsement_field_add") so different CRs' screenshots never collide.
    Full-page rather than a specific CSS selector: Streamlit's DOM structure
    for form widgets isn't a stable target to select against, and a live demo
    needs this to be robust more than it needs pixel-perfect framing.
    """
    mode = _screenshot_mode()
    path = _cache_path(namespace, stage)

    if mode == "replay":
        if not path.exists():
            raise ScreenshotError(
                f"no {stage} screenshot recording at {path} — run with "
                "SCREENSHOT_MODE=record first"
            )
        return path.read_bytes()

    png_bytes = _capture_live()
    if mode == "record":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(png_bytes)
    return png_bytes


def _capture_live() -> bytes:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise ScreenshotError(
            "playwright is not installed — pip install -r requirements.txt, then run "
            "`playwright install chromium` once per machine"
        ) from exc

    base_url = os.environ.get("MOCKAPP_URL", _DEFAULT_MOCKAPP_URL)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page()
                page.goto(base_url, timeout=_TIMEOUT_MS)
                page.wait_for_load_state("networkidle", timeout=_TIMEOUT_MS)
                return page.screenshot(full_page=True)
            finally:
                browser.close()
    except ScreenshotError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ScreenshotError(f"screenshot capture failed against {base_url}: {exc}") from exc
