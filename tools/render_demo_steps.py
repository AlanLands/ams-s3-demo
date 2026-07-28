"""Render demo/DEMO_STEPS.md to the styled HTML + PDF handed to other teams.

The markdown is the source of truth; `docs/S3_DEMO_STEPS.{html,pdf}` are
build outputs. Before this existed the PDF was hand-authored HTML, which meant
the repo's own copy and the copy people were sent drifted apart the moment
either was edited.

Two deliberate choices:

- **Stylesheet is read from `docs/S3_TEST_GUIDE.html`, not duplicated here.**
  That file is the house style for this project's PDFs; copying its CSS into
  this script would fork it on the first tweak.
- **`markdown-it-py` only.** It is already present (a transitive dependency of
  the pinned requirements), so doc rendering adds no new install for a
  locked-down environment — CLAUDE.md hard rule 4. Tables are enabled
  explicitly because the CommonMark preset leaves them off.

Usage:
    python tools/render_demo_steps.py            # writes html + pdf
    python tools/render_demo_steps.py --html-only

Chrome is only needed for the PDF step; `--html-only` works without it.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from markdown_it import MarkdownIt

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_MD = REPO_ROOT / "demo" / "DEMO_STEPS.md"
STYLE_SOURCE = REPO_ROOT / "docs" / "S3_TEST_GUIDE.html"
OUT_HTML = REPO_ROOT / "docs" / "S3_DEMO_STEPS.html"
OUT_PDF = REPO_ROOT / "docs" / "S3_DEMO_STEPS.pdf"

# Chrome ships under a different path on every OS; first hit wins. Kept as a
# list rather than a hard-coded macOS path so this survives the port to the
# hosting team's box.
CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
]

COVER = """<header class="cover">
  <div class="kicker">MapleSure Insurance · AMS Console</div>
  <h1>S3 Demo — Run Steps</h1>
  <p class="subtitle">Standing the demo up from a clean checkout, in any sandbox</p>
  <p class="meta">
    Generated from <span class="mono">demo/DEMO_STEPS.md</span> ·
    repo <span class="mono">ams-s3-demo</span><br>
    Companion docs: <span class="mono">apps/README.md</span> (what each application is) ·
    <span class="mono">demo/DEMO_TEST_GUIDE.md</span> (per-scenario rehearsal script)
  </p>
</header>
"""


def read_stylesheet() -> str:
    text = STYLE_SOURCE.read_text(encoding="utf-8")
    start = text.index("<style>")
    end = text.index("</style>") + len("</style>")
    return text[start:end]


def render_markdown(md_text: str) -> str:
    # Drop the H1 and the "this file is the source of truth" preamble: the PDF
    # has its own cover, and a build note aimed at repo readers is noise to
    # the person the PDF is sent to.
    md_text = re.sub(r"\A# .*?\n", "", md_text, count=1)
    md_text = re.sub(
        r"This file is the source of truth\..*?`tools/render_demo_steps\.py`\.\n",
        "",
        md_text,
        flags=re.S,
    )
    md = MarkdownIt("commonmark").enable("table")
    return md.render(md_text)


def style_callouts(html: str) -> str:
    """Turn blockquotes into the house callout blocks.

    Markdown has no callout syntax, so the source uses blockquotes: a leading
    "⚠" marks the warning variant, everything else is the standard accent
    block. Done as a post-pass rather than with a custom renderer rule because
    it is presentational only — the markdown stays readable as markdown.
    """
    def replace(match: re.Match) -> str:
        inner = match.group(1)
        warn = "⚠" in inner
        inner = inner.replace("⚠", "", 1)
        # First <strong> becomes the callout label.
        label_match = re.search(r"<strong>(.*?)</strong>", inner, flags=re.S)
        label_html = ""
        if label_match:
            label_html = f'<span class="label">{label_match.group(1)}</span>'
            inner = inner.replace(label_match.group(0), "", 1)
            # Tidy the separator left behind by "**Label** — text".
            inner = re.sub(r"(<p>)\s*(—|-)\s*", r"\1", inner, count=1)
            # "**Open this one** — the console UI is..." reads as one sentence
            # in markdown, but the label is lifted out into its own heading
            # here, so the remainder has to start as a sentence of its own.
            inner = re.sub(
                r"(<p>\s*)([a-z])",
                lambda m: m.group(1) + m.group(2).upper(),
                inner,
                count=1,
            )
        cls = "callout warn" if warn else "callout"
        return f'<div class="{cls}">{label_html}{inner}</div>'

    return re.sub(r"<blockquote>\s*(.*?)\s*</blockquote>", replace, html, flags=re.S)


def style_checklist(html: str) -> str:
    """Render `- [ ]` items with the house checkbox list instead of raw text."""
    if "[ ]" not in html:
        return html
    html = html.replace("<li>[ ] ", "<li>")
    # Only the pre-demo checklist uses task syntax, so tag the list that
    # contained it rather than every <ul> on the page.
    return re.sub(
        r"<ul>(\s*<li>(?:(?!</ul>).)*?You have walked beats.*?)</ul>",
        r'<ul class="check">\1</ul>',
        html,
        flags=re.S,
    )


def find_chrome() -> str | None:
    for candidate in CHROME_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    return None


def main() -> int:
    body = render_markdown(SOURCE_MD.read_text(encoding="utf-8"))
    body = style_callouts(body)
    body = style_checklist(body)
    # The trailing "---" rule before the closing paragraph reads as a footer.
    body = body.replace("<hr />\n<p>The four applications live",
                        '<p class="footer-note">The four applications live')

    html = (
        "<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<title>AMS S3 — Demo Run Steps</title>\n"
        f"{read_stylesheet()}\n</head>\n<body>\n\n{COVER}\n{body}\n</body>\n</html>\n"
    )
    OUT_HTML.write_text(html, encoding="utf-8")
    print(f"wrote {OUT_HTML.relative_to(REPO_ROOT)}")

    if "--html-only" in sys.argv:
        return 0

    chrome = find_chrome()
    if chrome is None:
        print("Chrome/Chromium not found — HTML written, PDF skipped.", file=sys.stderr)
        print(f"Looked in: {', '.join(CHROME_CANDIDATES)}", file=sys.stderr)
        return 1

    subprocess.run(
        [
            chrome,
            "--headless",
            "--disable-gpu",
            "--no-pdf-header-footer",
            f"--print-to-pdf={OUT_PDF}",
            OUT_HTML.as_uri(),
        ],
        check=True,
        capture_output=True,
    )
    print(f"wrote {OUT_PDF.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
