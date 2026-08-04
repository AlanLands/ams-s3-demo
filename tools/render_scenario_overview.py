"""Build the flow diagram on page 2 of docs/S3_SCENARIO_OVERVIEW.html, then render the PDF.

The diagram is five columns of stacked boxes joined by arrows: what comes in, what
AI does, where a person decides, what comes out, and the impact. It is generated
rather than hand-authored because the box geometry has to stay consistent across
five columns and every y-coordinate shifts when a single line of copy grows.

**Edit the copy in COLUMNS below, not in the HTML** — the HTML carries a
`<!-- FLOW-DIAGRAM-SLOT` marker and everything between it and the closing
`</div>` of that section is replaced wholesale on each run.

    python -m tools.render_scenario_overview          # rewrite the slot + render the PDF
    python -m tools.render_scenario_overview --check  # verify each page fits its print box

Text in SVG does not wrap, so every string below is one rendered line. The widest
line each box can take is printed by --check; keep AI bullets to ~25 characters
and the other boxes to ~27, or the text runs past its border. That overflow is
invisible in the source and only shows up in the rendered PDF.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import sys

from tools import scenario_stage_pages

REPO = pathlib.Path(__file__).resolve().parent.parent
HTML = REPO / "docs" / "S3_SCENARIO_OVERVIEW.html"
PDF = REPO / "docs" / "S3_SCENARIO_OVERVIEW.pdf"

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# --- the copy -----------------------------------------------------------------
# `ai` entries are (is_bullet, text); a 0 continues the previous bullet onto a
# second line rather than starting a new one.

COLUMNS = [
    dict(
        title="Impact analysis",
        inn=["The user story"],
        ai=[
            (1, "Reads story and code"),
            (1, "Asks what is unclear"),
            (1, "Sizes the job"),
            (1, "Checks 5 other systems"),
        ],
        person=["Answers, then accepts", "the assessment"],
        out=["An assessment, plus 1 job", "for the other team"],
        impact=["Wrong assumptions are", "caught before any", "code is written"],
    ),
    dict(
        title="Target selection",
        inn=["The assessment"],
        ai=[
            (1, "Finds the repository"),
            (1, "Narrows 9 files to 4"),
            (1, "Marks read-only files"),
            (1, "Checks out a copy"),
        ],
        person=["Confirms it, and", "checks it out"],
        out=["A working copy, and the", "files it may touch"],
        impact=["AI cannot wander into", "code this change has", "nothing to do with"],
    ),
    dict(
        title="Code generation",
        inn=["The working copy"],
        ai=[
            (1, "Works on a branch"),
            (1, "Edits 4 files, each"),
            (0, "with a reason"),
            (1, "Answers “why did you?”"),
        ],
        person=["Reviews, questions, then", "approves or rejects"],
        out=["A reviewed change, plus", "a design document"],
        impact=["The reviewer can ask", "the author why — the", "author is still there"],
    ),
    dict(
        title="Test",
        inn=["The applied change"],
        ai=[
            (1, "Drafts the test plan"),
            (1, "Writes and runs tests"),
            (1, "Re-runs 27 older tests"),
        ],
        person=["Tester edits and approves", "the plan before any test", "code exists"],
        out=["Results, plus proof each", "requirement was checked"],
        impact=["Nothing else broke —", "and that is proven,", "not claimed"],
    ),
    dict(
        title="Release",
        inn=["Green test results"],
        ai=[
            (1, "Writes the release notes"),
            (1, "Writes the go-live steps"),
            (1, "Writes how to undo it"),
        ],
        person=["Approves the release and", "closes the job off"],
        out=["A release note, plus a", "go-live and rollback plan"],
        impact=["The paperwork matches", "what actually happened"],
    ),
]

# --- geometry, in viewBox units (1000 units == the 273mm print content width) ---

W, GAP, PAD = 184, 16, 9
X0 = [8 + i * (W + GAP) for i in range(5)]
CX = [x + W / 2 for x in X0]
IW = W - 2 * PAD

CARD_T, CARD_B, HEAD_H = 48, 496, 28
IN_T, IN_H = 86, 44
AI_T, AI_H = 146, 104
PE_T, PE_H = 266, 74
OU_T, OU_H = 356, 48
IM_T, IM_H = 420, 62
VIEW_H = 514

ACC, OK, INK, SOFT, FAINT = "#8b1e2d", "#1c6b3c", "#1a1a1a", "#5c5c5c", "#8a8a8a"
FONT = 'font-family="-apple-system, BlinkMacSystemFont, Helvetica, Arial, sans-serif"'


def build_svg() -> str:
    out: list[str] = []
    add = out.append

    add(f'<svg class="fig" viewBox="0 0 1000 {VIEW_H}" role="img"')
    add('     aria-label="For each of the five steps: what comes in, what AI does, where a '
        'person decides, what comes out, and the impact.">')
    add("  <defs>")
    add('    <marker id="f-down" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6.5" '
        'markerHeight="6.5" orient="auto-start-reverse">')
    add('      <path d="M0 0 10 5 0 10z" fill="#a8a8a8"/></marker>')
    add('    <marker id="f-side" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
        'markerHeight="7" orient="auto-start-reverse">')
    add('      <path d="M0 0 10 5 0 10z" fill="#c0c0c0"/></marker>')
    add("  </defs>")
    add(f"  <g {FONT}>")

    # the spine across the top: REQUEST -> 1..5 -> LIVE
    add('    <rect x="0" y="6" width="58" height="28" rx="14" fill="#fff" stroke="#b3b3b3"/>')
    add(f'    <text x="29" y="25" text-anchor="middle" font-size="11" font-weight="700" '
        f'fill="{SOFT}" letter-spacing="0.5">REQUEST</text>')
    add('    <path d="M58 20 H72" stroke="#c0c0c0" stroke-width="2.5" fill="none" '
        'marker-end="url(#f-side)"/>')
    for i in range(5):
        add(f'    <circle cx="{CX[i]:g}" cy="20" r="14" fill="{ACC}"/>')
        add(f'    <text x="{CX[i]:g}" y="25.5" text-anchor="middle" font-size="14" '
            f'font-weight="700" fill="#fff">{i + 1}</text>')
        if i < 4:
            add(f'    <path d="M{CX[i] + 14:g} 20 H{CX[i + 1] - 18:g}" stroke="#c0c0c0" '
                'stroke-width="2.5" fill="none" marker-end="url(#f-side)"/>')
        add(f'    <path d="M{CX[i]:g} 34 V{CARD_T - 4}" stroke="#a8a8a8" stroke-width="2" '
            'fill="none" marker-end="url(#f-down)"/>')
    add('    <path d="M914 20 H936" stroke="#c0c0c0" stroke-width="2.5" fill="none" '
        'marker-end="url(#f-side)"/>')
    add(f'    <rect x="942" y="6" width="58" height="28" rx="14" fill="#edf5f0" stroke="{OK}"/>')
    add(f'    <text x="971" y="25" text-anchor="middle" font-size="11" font-weight="700" '
        f'fill="{OK}" letter-spacing="0.5">LIVE</text>')

    def arrow(cx: float, y1: int, y2: int) -> None:
        add(f'    <path d="M{cx:g} {y1} V{y2}" stroke="#a8a8a8" stroke-width="2" fill="none" '
            'marker-end="url(#f-down)"/>')

    for i, col in enumerate(COLUMNS):
        x, cx, tx = X0[i], CX[i], X0[i] + PAD

        add(f'    <rect x="{x}" y="{CARD_T}" width="{W}" height="{CARD_B - CARD_T}" rx="5" '
            'fill="#fff" stroke="#d8d8d8"/>')
        add(f'    <path d="M{x} {CARD_T + 5} a5 5 0 0 1 5 -5 h{W - 10} a5 5 0 0 1 5 5 '
            f'v{HEAD_H - 5} h-{W} z" fill="{ACC}"/>')
        add(f'    <text x="{cx:g}" y="{CARD_T + 19}" text-anchor="middle" font-size="12.5" '
            f'font-weight="700" fill="#fff">{col["title"]}</text>')

        add(f'    <rect x="{tx}" y="{IN_T}" width="{IW}" height="{IN_H}" rx="3" fill="#f4f4f2" '
            'stroke="#cfcfcf"/>')
        add(f'    <text x="{tx + 8}" y="{IN_T + 15}" font-size="8.5" font-weight="700" '
            f'fill="{FAINT}" letter-spacing="0.9">COMES IN</text>')
        for k, line in enumerate(col["inn"]):
            add(f'    <text x="{tx + 8}" y="{IN_T + 31 + k * 14}" font-size="11.5" data-maxw="{IW - 16}" '
                f'fill="{INK}">{line}</text>')
        arrow(cx, IN_T + IN_H, AI_T - 4)

        add(f'    <rect x="{tx}" y="{AI_T}" width="{IW}" height="{AI_H}" rx="3" fill="#fff" '
            f'stroke="{ACC}" stroke-width="1.5"/>')
        add(f'    <text x="{tx + 8}" y="{AI_T + 16}" font-size="8.5" font-weight="700" '
            f'fill="{ACC}" letter-spacing="0.9">AI DOES</text>')
        for k, (bullet, line) in enumerate(col["ai"]):
            y = AI_T + 34 + k * 17
            if bullet:
                add(f'    <circle cx="{tx + 11}" cy="{y - 4}" r="2.2" fill="{ACC}"/>')
            add(f'    <text x="{tx + 19}" y="{y}" font-size="11.5" fill="{INK}" '
                f'data-maxw="{IW - 19}">{line}</text>')
        arrow(cx, AI_T + AI_H, PE_T - 4)

        add(f'    <rect x="{tx}" y="{PE_T}" width="{IW}" height="{PE_H}" rx="3" fill="#edf5f0" '
            f'stroke="{OK}" stroke-width="1.5"/>')
        add(f'    <text x="{tx + 8}" y="{PE_T + 16}" font-size="8.5" font-weight="700" '
            f'fill="{OK}" letter-spacing="0.9">A PERSON DECIDES</text>')
        for k, line in enumerate(col["person"]):
            add(f'    <text x="{tx + 8}" y="{PE_T + 32 + k * 14}" font-size="11.5" data-maxw="{IW - 16}" '
                f'fill="#2f5741">{line}</text>')
        arrow(cx, PE_T + PE_H, OU_T - 4)

        add(f'    <rect x="{tx}" y="{OU_T}" width="{IW}" height="{OU_H}" rx="3" fill="#fcfcfb" '
            'stroke="#b8b8b8" stroke-dasharray="5 3"/>')
        add(f'    <text x="{tx + 8}" y="{OU_T + 15}" font-size="8.5" font-weight="700" '
            f'fill="{FAINT}" letter-spacing="0.9">YOU GET</text>')
        for k, line in enumerate(col["out"]):
            add(f'    <text x="{tx + 8}" y="{OU_T + 31 + k * 14}" font-size="11.5" data-maxw="{IW - 16}" '
                f'fill="{INK}">{line}</text>')
        arrow(cx, OU_T + OU_H, IM_T - 4)

        add(f'    <rect x="{tx}" y="{IM_T}" width="{IW}" height="{IM_H}" rx="3" fill="#f6ecee"/>')
        add(f'    <rect x="{tx}" y="{IM_T}" width="3" height="{IM_H}" fill="{ACC}"/>')
        add(f'    <text x="{tx + 10}" y="{IM_T + 15}" font-size="8.5" font-weight="700" '
            f'fill="{ACC}" letter-spacing="0.9">THE IMPACT</text>')
        for k, line in enumerate(col["impact"]):
            add(f'    <text x="{tx + 10}" y="{IM_T + 31 + k * 14}" font-size="12" data-maxw="{IW - 19}" '
                f'font-weight="600" fill="{INK}">{line}</text>')

    add("  </g>")
    add("</svg>")
    return "\n".join(out)


SLOT = re.compile(
    r"(?P<open>  <!-- FLOW-DIAGRAM-SLOT.*?-->\n)(?P<body>.*?)(?P<close>\n</div>\n\n</div>)",
    re.DOTALL,
)

DETAIL_SLOT = re.compile(
    r"(?P<open><!-- DETAIL-PAGES-SLOT.*?-->\n)(?P<body>.*?)(?P<close><!-- CLOSING-PAGE -->)",
    re.DOTALL,
)

PAGE_COUNT = 9  # orientation + cover + overview + five stages + closing


def write_html() -> None:
    text = HTML.read_text()

    match = SLOT.search(text)
    if not match:
        sys.exit("FLOW-DIAGRAM-SLOT marker not found in " + str(HTML))
    svg = "\n".join("  " + line if line else line for line in build_svg().splitlines())
    text = text[: match.start("body")] + "\n" + svg + text[match.end("body") :]

    match = DETAIL_SLOT.search(text)
    if not match:
        sys.exit("DETAIL-PAGES-SLOT marker not found in " + str(HTML))
    text = (text[: match.start("body")] + "\n" + scenario_stage_pages.build_pages() + "\n\n"
            + text[match.end("body") :])

    HTML.write_text(text)


def render_pdf() -> None:
    if not pathlib.Path(CHROME).exists():
        sys.exit("Chrome not found at " + CHROME)
    subprocess.run(
        [CHROME, "--headless", "--disable-gpu", "--no-pdf-header-footer",
         f"--print-to-pdf={PDF}", f"file://{HTML}"],
        check=True, capture_output=True,
    )
    raw = PDF.read_bytes()
    pages = raw.count(b"/Type /Page") - raw.count(b"/Type /Pages")
    print(f"{PDF.relative_to(REPO)}: {pages} pages, {len(raw):,} bytes")
    if pages != PAGE_COUNT:
        sys.exit(f"expected {PAGE_COUNT} pages, got {pages} — a page has overflowed")


def check_fit() -> None:
    """Measure each page against the print box. Overflow silently adds a page."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit("playwright is not installed; skip --check or install it")

    width = round((297 - 24) / 25.4 * 96)
    limit = (210 - 22) / 25.4 * 96
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": 800})
        page.emulate_media(media="print")
        page.goto(f"file://{HTML}")
        count = page.evaluate("() => document.querySelectorAll('.page').length")
        bad = False
        for i in range(count):
            h = page.evaluate(
                "i => document.querySelectorAll('.page')[i].getBoundingClientRect().height", i
            )
            state = "ok" if h <= limit else f"OVER by {h - limit:.1f}px"
            if h > limit:
                bad = True
            print(f"  page {i + 1}: {h:6.1f} / {limit:.1f}px  {state}")
        overflow = page.evaluate("""() => {
          const bad = [];
          for (const t of document.querySelectorAll('text[data-maxw]')) {
            const max = parseFloat(t.dataset.maxw);
            const len = t.getComputedTextLength();
            if (len > max) bad.push({text: t.textContent, over: +(len - max).toFixed(1), max: max});
          }
          return bad;
        }""")
        browser.close()
    for item in overflow:
        print(f"  OVERFLOW +{item['over']:>5}u (max {item['max']:g}): {item['text']}")
    if overflow:
        bad = True
        print(f"  {len(overflow)} string(s) run past their box")
    if bad:
        sys.exit("layout check failed")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="only measure page fit")
    args = parser.parse_args()
    if args.check:
        check_fit()
        return
    write_html()
    check_fit()
    render_pdf()


if __name__ == "__main__":
    main()
