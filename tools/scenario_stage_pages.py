"""The five per-stage pages of docs/S3_SCENARIO_OVERVIEW.html.

Each stage gets one landscape page with the same two-part shape:

  * a top band — COMES IN -> AI DOES -> A PERSON DECIDES -> YOU GET, four boxes
    joined by arrows, identical geometry on every page so the reader learns it once;
  * a bottom band — the diagram specific to that stage, which is the reason the
    page exists (how the other-systems check is decided, how the file list narrows,
    the review loop, the two test suites, the commit gate).

Called by tools/render_scenario_overview.py. Copy lives in STAGES below.

SVG text does not wrap, so every string here is one rendered line. Budgets at
font-size 11.5 in the top band: COMES IN ~27 characters, AI DOES ~47,
A PERSON DECIDES ~39, YOU GET ~30. Overrunning is invisible in the source and
only shows up as text crossing a border in the rendered PDF — always read it back.
"""

from __future__ import annotations

ACC, OK, INK, SOFT, FAINT = "#8b1e2d", "#1c6b3c", "#1a1a1a", "#5c5c5c", "#8a8a8a"
RED_SOFT, OK_SOFT, PAPER = "#f6ecee", "#edf5f0", "#fcfcfb"
FONT = 'font-family="-apple-system, BlinkMacSystemFont, Helvetica, Arial, sans-serif"'

# top-band geometry
BAND_T, BAND_H = 26, 142
BOXES = [(0, 176), (208, 300), (540, 240), (812, 188)]
TAGS = [("COMES IN", FAINT, "#f4f4f2", "#cfcfcf"),
        ("AI DOES", ACC, "#fff", ACC),
        ("A PERSON DECIDES", OK, OK_SOFT, OK),
        ("YOU GET", FAINT, PAPER, "#b8b8b8")]


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _top_band(stage: dict) -> list[str]:
    out: list[str] = []
    add = out.append
    content = [stage["inn"], stage["ai"], stage["person"], stage["out"]]

    for i, ((x, w), (tag, colour, fill, stroke)) in enumerate(zip(BOXES, TAGS)):
        dashed = ' stroke-dasharray="5 3"' if i == 3 else ""
        width = "1.5" if i in (1, 2) else "1"
        add(f'    <rect x="{x}" y="{BAND_T}" width="{w}" height="{BAND_H}" rx="4" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="{width}"{dashed}/>')
        add(f'    <text x="{x + 10}" y="{BAND_T + 17}" font-size="8.5" font-weight="700" '
            f'fill="{colour}" letter-spacing="0.9">{tag}</text>')

        if i == 1:  # numbered sub-steps
            for k, line in enumerate(content[i]):
                y = BAND_T + 39 + k * 24
                add(f'    <circle cx="{x + 17}" cy="{y - 4}" r="7.5" fill="{ACC}"/>')
                add(f'    <text x="{x + 17}" y="{y - 0.5}" text-anchor="middle" font-size="9" '
                    f'font-weight="700" fill="#fff">{k + 1}</text>')
                add(f'    <text x="{x + 31}" y="{y}" font-size="11.5" fill="{INK}" '
                    f'data-maxw="{w - 41}">{_esc(line)}</text>')
        else:
            body = "#2f5741" if i == 2 else INK
            for k, line in enumerate(content[i]):
                add(f'    <text x="{x + 10}" y="{BAND_T + 36 + k * 16}" font-size="11.5" '
                    f'fill="{body}" data-maxw="{w - 20}">{_esc(line)}</text>')

    mid = BAND_T + BAND_H / 2
    for x0, x1 in ((176, 204), (508, 536), (780, 808)):
        add(f'    <path d="M{x0} {mid:g} H{x1}" stroke="#a8a8a8" stroke-width="2.2" fill="none" '
            'marker-end="url(#d-side)"/>')
    return out


def _band_title(text: str, y: int) -> list[str]:
    return [f'    <text x="0" y="{y}" font-size="12.5" font-weight="700" fill="{ACC}">{text}</text>',
            f'    <path d="M0 {y + 7} H1000" stroke="#e2e2e2" stroke-width="1"/>']


# --- per-stage bottom bands ---------------------------------------------------

# Ordered so the three "no" systems are contiguous — the outcome box beneath them
# spans all three, which only works if they sit next to each other.
SYSTEMS = [
    ("EnrolDirect", "THIS ONE", "The change itself", "self"),
    ("DocumentHub", "YES", "Must word a pack it has never written.", "yes"),
    ("PolicyCore", "NO", "Upstream. Nothing it holds changes.", "no"),
    ("NightlyBatch", "NO", "Its totals move. Its code does not.", "no"),
    ("IntegrationBridge", "NO", "Carries the value on a field it has.", "no"),
]


def _band_systems(y0: int) -> tuple[list[str], int]:
    out = _band_title("How it decides whether another team is actually affected", y0)
    add = out.append
    top = y0 + 26
    w, gap = 188, 15
    for i, (name, verdict, why, kind) in enumerate(SYSTEMS):
        x = i * (w + gap)
        fill, stroke = (PAPER, "#d8d8d8")
        chip, chip_fg = "#efefef", SOFT
        if kind == "yes":
            fill, stroke, chip, chip_fg = OK_SOFT, OK, OK, "#fff"
        elif kind == "self":
            fill, stroke, chip, chip_fg = RED_SOFT, ACC, ACC, "#fff"
        add(f'    <rect x="{x}" y="{top}" width="{w}" height="86" rx="4" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="1.4"/>')
        add(f'    <text x="{x + 10}" y="{top + 20}" font-size="12" font-weight="700" '
            f'fill="{INK}">{name}</text>')
        cw = 62 if kind == "self" else (38 if verdict == "YES" else 34)
        add(f'    <rect x="{x + 10}" y="{top + 28}" width="{cw}" height="17" rx="8.5" '
            f'fill="{chip}"/>')
        add(f'    <text x="{x + 10 + cw / 2:g}" y="{top + 40}" text-anchor="middle" '
            f'font-size="9" font-weight="700" fill="{chip_fg}" letter-spacing="0.6">'
            f'{verdict}</text>')
        for k, line in enumerate(_wrap(why, 26)):
            add(f'    <text x="{x + 10}" y="{top + 61 + k * 13}" font-size="10" '
                f'fill="{SOFT}">{line}</text>')

    # outcomes: one box under the single YES, one spanning the three NOs
    oy = top + 110
    yes_x = w + gap
    no_x = 2 * (w + gap)
    add(f'    <path d="M{yes_x + w / 2:g} {top + 86} V{oy - 4}" stroke="{OK}" '
        'stroke-width="2.2" fill="none" marker-end="url(#d-down-ok)"/>')
    for i in (2, 3, 4):
        add(f'    <path d="M{i * (w + gap) + w / 2:g} {top + 86} V{oy - 4}" stroke="#a8a8a8" '
            'stroke-width="1.8" fill="none" stroke-dasharray="5 3" marker-end="url(#d-down)"/>')

    add(f'    <rect x="{yes_x}" y="{oy}" width="{w}" height="32" rx="4" '
        f'fill="{OK_SOFT}" stroke="{OK}" stroke-width="1.4"/>')
    add(f'    <text x="{yes_x + w / 2:g}" y="{oy + 21}" text-anchor="middle" font-size="11" '
        f'font-weight="700" fill="{OK}">A job is raised for them</text>')
    add(f'    <rect x="{no_x}" y="{oy}" width="{3 * w + 2 * gap}" height="32" rx="4" '
        'fill="#fff" stroke="#c8c8c8" stroke-dasharray="5 3"/>')
    add(f'    <text x="{no_x + (3 * w + 2 * gap) / 2:g}" y="{oy + 21}" text-anchor="middle" '
        f'font-size="11" fill="{SOFT}">Recorded, each with the reason no job was raised — the '
        'estate map is not the job list</text>')

    y = oy + 46
    add(f'    <rect x="0" y="{y}" width="1000" height="30" rx="4" fill="{RED_SOFT}"/>')
    add(f'    <rect x="0" y="{y}" width="3" height="30" fill="{ACC}"/>')
    add(f'    <text x="14" y="{y + 20}" font-size="11.5" font-weight="600" fill="{INK}">'
        'The bar is “that team must change code”, not “that team is affected”. Three of these are '
        'affected and have nothing to do — raising jobs for them wastes three teams’ time.</text>')
    return out, y + 38


FUNNEL = [
    (1000, "9 files in the application", "Everything EnrolDirect is made of", "#e6e6e6", INK),
    (760, "6 files central to this change", "What AI is given to read", "#e2b9c0", INK),
    (500, "4 files AI may edit", "The only files it can write to", ACC, "#fff"),
    (280, "2 files it may read but never edit", "Including the earlier analysis", "#7a7a7a", "#fff"),
]


def _band_funnel(y0: int) -> tuple[list[str], int]:
    out = _band_title("How the file list narrows before a single line is written", y0)
    add = out.append
    top = y0 + 26
    for i, (w, label, note, fill, fg) in enumerate(FUNNEL):
        y = top + i * 42
        add(f'    <rect x="0" y="{y}" width="{w}" height="34" rx="3" fill="{fill}"/>')
        add(f'    <text x="14" y="{y + 22}" font-size="12.5" font-weight="700" fill="{fg}">'
            f'{label}</text>')
        add(f'    <text x="{w + 14}" y="{y + 22}" font-size="11" fill="{SOFT}">{note}</text>')
        if i < len(FUNNEL) - 1:
            add(f'    <path d="M40 {y + 34} V{y + 38}" stroke="#a8a8a8" stroke-width="2" '
                'fill="none" marker-end="url(#d-down)"/>')
    y = top + len(FUNNEL) * 42 + 4
    add(f'    <rect x="0" y="{y}" width="1000" height="30" rx="4" fill="{RED_SOFT}"/>')
    add(f'    <rect x="0" y="{y}" width="3" height="30" fill="{ACC}"/>')
    add(f'    <text x="14" y="{y + 20}" font-size="11.5" font-weight="600" fill="{INK}">'
        'A read-only file that comes back changed fails the run outright — the AI cannot quietly '
        'widen its own permissions.</text>')
    return out, y + 38


def _band_loop(y0: int) -> tuple[list[str], int]:
    out = _band_title("The review loop — nothing reaches the repository until a person says so", y0)
    add = out.append
    top = y0 + 30
    # Three decision boxes stacked on the right; the two that send the work back
    # loop underneath rather than over the top — routing them above ran the arrow
    # straight through the band title and the YOU GET box.
    dec_y = [top, top + 52, top + 104]
    dec_x, dec_w = 552, 264

    for x, w, title, sub, stroke, fill in [
        (74, 190, "AI proposes", "a change, with a\nreason per file", ACC, RED_SOFT),
        (312, 190, "The reviewer reads it", "green is added,\nred is removed", "#c8c8c8", "#fff"),
    ]:
        add(f'    <rect x="{x}" y="{dec_y[1]}" width="{w}" height="52" rx="4" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="1.5"/>')
        add(f'    <text x="{x + 12}" y="{dec_y[1] + 21}" font-size="12.5" font-weight="700" '
            f'fill="{INK}">{title}</text>')
        for k, line in enumerate(sub.split("\n")):
            add(f'    <text x="{x + 12}" y="{dec_y[1] + 36 + k * 12}" font-size="10" '
                f'fill="{SOFT}">{line}</text>')
    add(f'    <path d="M264 {dec_y[1] + 26} H308" stroke="#a8a8a8" stroke-width="2.2" '
        'fill="none" marker-end="url(#d-side)"/>')

    outs = [("Asks “why did you do this?”", "AI answers on the spot", OK),
            ("Rejects it", "AI proposes a different change", ACC),
            ("Applies it", "the change lands on the branch", OK)]
    for k, (label, sub, colour) in enumerate(outs):
        y = dec_y[k]
        add(f'    <rect x="{dec_x}" y="{y}" width="{dec_w}" height="44" rx="4" fill="#fff" '
            f'stroke="{colour}" stroke-width="1.4"/>')
        add(f'    <text x="{dec_x + 12}" y="{y + 19}" font-size="11.5" font-weight="700" '
            f'fill="{colour}">{label}</text>')
        add(f'    <text x="{dec_x + 12}" y="{y + 34}" font-size="10" fill="{SOFT}">{sub}</text>')
        add(f'    <path d="M502 {dec_y[1] + 26} C528 {dec_y[1] + 26} 528 {y + 22} '
            f'{dec_x - 4} {y + 22}" stroke="#a8a8a8" stroke-width="2" fill="none" '
            'marker-end="url(#d-side)"/>')

    # the applied outcome, level with "Applies it"
    add(f'    <rect x="{dec_x + dec_w + 32}" y="{dec_y[2]}" width="152" height="44" rx="4" '
        f'fill="{OK_SOFT}" stroke="{OK}" stroke-width="1.5"/>')
    add(f'    <text x="{dec_x + dec_w + 44}" y="{dec_y[2] + 19}" font-size="11.5" '
        f'font-weight="700" fill="{OK}">Applied to the branch</text>')
    add(f'    <text x="{dec_x + dec_w + 44}" y="{dec_y[2] + 34}" font-size="10" fill="{SOFT}">'
        'and the app restarts</text>')
    add(f'    <path d="M{dec_x + dec_w} {dec_y[2] + 22} H{dec_x + dec_w + 28}" stroke="{OK}" '
        'stroke-width="2.2" fill="none" marker-end="url(#d-side-ok)"/>')

    # the loop-back, routed below everything
    loop_y = dec_y[2] + 74
    add(f'    <path d="M{dec_x + dec_w} {dec_y[0] + 22} H{dec_x + dec_w + 16} '
        f'V{loop_y} H169 V{dec_y[1] + 56}" stroke="{SOFT}" stroke-width="1.8" fill="none" '
        'stroke-dasharray="5 4" marker-end="url(#d-down)"/>')
    add(f'    <path d="M{dec_x + dec_w} {dec_y[1] + 22} H{dec_x + dec_w + 16}" '
        f'stroke="{SOFT}" stroke-width="1.8" fill="none" stroke-dasharray="5 4"/>')
    add(f'    <text x="300" y="{loop_y - 7}" font-size="10.5" font-weight="700" fill="{SOFT}">'
        'back to the AI, as many times as the reviewer wants</text>')
    return out, loop_y + 22


def _band_suites(y0: int) -> tuple[list[str], int]:
    out = _band_title("Two suites — and AI is allowed to write only one of them", y0)
    add = out.append
    top = y0 + 26
    panes = [
        (0, 488, ACC, "#fff", "Tests AI wrote for this change",
         ["Proves the new behaviour works —", "a prospect now gets through"], "AI writes these"),
        (512, 488, OK, OK_SOFT, "27 tests people wrote, long before this",
         ["Proves nothing else broke —", "members and guests are untouched"], "AI may not write here"),
    ]
    for x, w, stroke, fill, title, lines, tag in panes:
        add(f'    <rect x="{x}" y="{top}" width="{w}" height="94" rx="4" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="1.6"/>')
        add(f'    <text x="{x + 14}" y="{top + 25}" font-size="13" font-weight="700" '
            f'fill="{INK}">{title}</text>')
        for k, line in enumerate(lines):
            add(f'    <text x="{x + 14}" y="{top + 46 + k * 15}" font-size="11" fill="{SOFT}">'
                f'{line}</text>')
        add(f'    <rect x="{x + 14}" y="{top + 66}" width="{9 * len(tag) + 16}" height="18" '
            f'rx="9" fill="{stroke}"/>')
        add(f'    <text x="{x + 22}" y="{top + 79}" font-size="9.5" font-weight="700" '
            f'fill="#fff" letter-spacing="0.5">{tag}</text>')

    y = top + 118
    for x in (244, 756):
        add(f'    <path d="M{x} {top + 94} V{y - 4}" stroke="#a8a8a8" stroke-width="2.2" '
            'fill="none" marker-end="url(#d-down)"/>')
    add(f'    <rect x="244" y="{y}" width="512" height="32" rx="4" fill="{OK_SOFT}" '
        f'stroke="{OK}" stroke-width="1.5"/>')
    add(f'    <text x="500" y="{y + 21}" text-anchor="middle" font-size="12" font-weight="700" '
        f'fill="{OK}">Both must pass before the change can be committed</text>')
    add(f'    <rect x="0" y="{y + 44}" width="1000" height="30" rx="4" fill="{RED_SOFT}"/>')
    add(f'    <rect x="0" y="{y + 44}" width="3" height="30" fill="{ACC}"/>')
    add(f'    <text x="14" y="{y + 64}" font-size="11.5" font-weight="600" fill="{INK}">'
        'A bug is then put into the code on purpose, to prove these tests would actually have '
        'caught it. Passing tests that catch nothing are worse than none.</text>')
    return out, y + 82


def _band_gate(y0: int) -> tuple[list[str], int]:
    out = _band_title("The gate before anything is committed", y0)
    add = out.append
    top = y0 + 30
    add(f'    <rect x="0" y="{top + 16}" width="250" height="58" rx="4" fill="#fff" '
        f'stroke="{ACC}" stroke-width="1.6"/>')
    add(f'    <text x="14" y="{top + 40}" font-size="12.5" font-weight="700" fill="{INK}">'
        'Did the tests pass?</text>')
    add(f'    <text x="14" y="{top + 58}" font-size="10.5" fill="{SOFT}">'
        'read from the job’s own history</text>')

    add(f'    <path d="M250 {top + 34} C300 {top + 34} 300 {top + 12} 348 {top + 12}" '
        f'stroke="{OK}" stroke-width="2.2" fill="none" marker-end="url(#d-side-ok)"/>')
    add(f'    <text x="284" y="{top + 8}" font-size="10" font-weight="700" fill="{OK}">YES</text>')
    add(f'    <path d="M250 {top + 56} C300 {top + 56} 300 {top + 96} 348 {top + 96}" '
        f'stroke="{ACC}" stroke-width="2.2" fill="none" stroke-dasharray="6 4" '
        'marker-end="url(#d-side-red)"/>')
    add(f'    <text x="284" y="{top + 112}" font-size="10" font-weight="700" fill="{ACC}">NO</text>')

    add(f'    <rect x="352" y="{top - 8}" width="230" height="42" rx="4" fill="{OK_SOFT}" '
        f'stroke="{OK}" stroke-width="1.5"/>')
    add(f'    <text x="366" y="{top + 18}" font-size="12" font-weight="700" fill="{OK}">'
        'Commit and push allowed</text>')
    add(f'    <rect x="352" y="{top + 76}" width="230" height="42" rx="4" fill={chr(34)}'
        f'{RED_SOFT}{chr(34)} stroke="{ACC}" stroke-width="1.5"/>')
    add(f'    <text x="366" y="{top + 102}" font-size="12" font-weight="700" fill="{ACC}">'
        'Blocked — and it says why</text>')

    add(f'    <path d="M582 {top + 13} H626" stroke="{OK}" stroke-width="2.2" fill="none" '
        'marker-end="url(#d-side-ok)"/>')
    steps = ["Branch", "Commit", "Push", "Release"]
    for k, label in enumerate(steps):
        x = 630 + k * 94
        add(f'    <rect x="{x}" y="{top - 6}" width="82" height="38" rx="4" fill="#fff" '
            'stroke="#c8c8c8" stroke-width="1.3"/>')
        add(f'    <text x="{x + 41}" y="{top + 18}" text-anchor="middle" font-size="11.5" '
            f'font-weight="700" fill="{INK}">{label}</text>')
        if k < len(steps) - 1:
            add(f'    <path d="M{x + 82} {top + 13} H{x + 90}" stroke="#a8a8a8" '
                'stroke-width="2" fill="none" marker-end="url(#d-side)"/>')

    y = top + 134
    add(f'    <rect x="0" y="{y}" width="1000" height="30" rx="4" fill={chr(34)}{RED_SOFT}'
        f'{chr(34)}/>')
    add(f'    <rect x="0" y="{y}" width="3" height="30" fill="{ACC}"/>')
    add(f'    <text x="14" y="{y + 20}" font-size="11.5" font-weight="600" fill="{INK}">'
        'The answer is read from the job’s own history — never from the screen. A screen that '
        'could claim “tests passed” could commit a broken change.</text>')
    return out, y + 38


# --- the stages ---------------------------------------------------------------

STAGES = [
    dict(
        num=1, name="Impact analysis",
        lead="What has to change, how big it is, and who else it touches — worked out before "
             "anyone opens an editor.",
        inn=["The story from the board", "The application source code"],
        ai=["Reads the story and the code together",
            "Asks the business what the story omits",
            "Names what must change, and sizes it",
            "Checks every system that depends on this one"],
        person=["Answers the questions AI raised", "Accepts the assessment",
                "Hands the job to an engineer"],
        out=["A written assessment", "A job for one other team",
             "The ticket moves itself on"],
        band=_band_systems,
    ),
    dict(
        num=2, name="Target selection",
        lead="Which repository the work belongs in, and which files inside it AI is even allowed "
             "to look at.",
        inn=["The accepted assessment", "Every repository we have"],
        ai=["Works out which repository it belongs to",
            "Narrows it to the files worth reading",
            "Splits editable files from read-only ones",
            "Checks out a working copy to change"],
        person=["Confirms the repository is the right one", "Checks it out"],
        out=["A working copy of EnrolDirect",
             "The files it may touch"],
        band=_band_funnel,
    ),
    dict(
        num=3, name="Code generation",
        lead="The change itself — written on a branch, explained line by line, and applied only "
             "when a person agrees.",
        inn=["The working copy", "The list of files it may edit"],
        ai=["Opens a separate branch — never the main line",
            "Writes it file by file, with a reason each",
            "Checks it touched only allowed files",
            "Answers questions about any line of it"],
        person=["Reads the difference, green and red", "Asks the AI why it did something",
                "Requests changes, applies, or rejects"],
        out=["A reviewed change",
             "A design document",
             "The app running the new code"],
        band=_band_loop,
    ),
    dict(
        num=4, name="Test",
        lead="Proving the new behaviour works, and — separately — proving nothing else broke.",
        inn=["The applied change", "The design document"],
        ai=["Drafts the scenarios, good cases and bad",
            "Writes test code only once approved",
            "Runs it, then re-runs the 27 tests people wrote",
            "Maps each requirement to its test"],
        person=["Tester edits and approves the plan", "— before any test code exists",
                "Reviews the results"],
        out=["Test results", "A regression pass",
             "A traceability matrix"],
        band=_band_suites,
    ),
    dict(
        num=5, name="Release",
        lead="Everything needed to put it live, assembled from what the run actually did.",
        inn=["Green test results", "The reviewed change"],
        ai=["Writes the release note, three audiences",
            "Works out the go-live order",
            "Writes the steps to undo it if it goes wrong",
            "Records what this release did not prove"],
        person=["Approves the release", "Closes the job off"],
        out=["A release note", "A go-live and rollback plan",
             "A release record"],
        band=_band_gate,
    ),
]


def build_pages() -> str:
    """Return the five stage pages as HTML."""
    pages: list[str] = []
    for stage in STAGES:
        body = _top_band(stage)
        band, height = stage["band"](BAND_T + BAND_H + 34)
        body += band
        svg = [f'  <svg class="fig" viewBox="0 0 1000 {height}" role="img"',
               f'       aria-label="Stage {stage["num"]}, {stage["name"]}: what comes in, what AI '
               'does, where a person decides, what comes out, and how the stage works.">',
               "    <defs>",
               '      <marker id="d-side" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
               'markerHeight="7" orient="auto-start-reverse">'
               f'<path d="M0 0 10 5 0 10z" fill="#a8a8a8"/></marker>',
               '      <marker id="d-side-ok" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
               'markerHeight="7" orient="auto-start-reverse">'
               f'<path d="M0 0 10 5 0 10z" fill="{OK}"/></marker>',
               '      <marker id="d-side-red" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
               'markerHeight="7" orient="auto-start-reverse">'
               f'<path d="M0 0 10 5 0 10z" fill="{ACC}"/></marker>',
               '      <marker id="d-down" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6.5" '
               'markerHeight="6.5" orient="auto-start-reverse">'
               f'<path d="M0 0 10 5 0 10z" fill="#a8a8a8"/></marker>',
               '      <marker id="d-down-ok" viewBox="0 0 10 10" refX="9" refY="5" '
               'markerWidth="6.5" markerHeight="6.5" orient="auto-start-reverse">'
               f'<path d="M0 0 10 5 0 10z" fill="{OK}"/></marker>',
               "    </defs>",
               f"    <g {FONT}>"] + body + ["    </g>", "  </svg>"]

        pages.append(
            f'<!-- ==================== STAGE {stage["num"]} · {stage["name"].upper()} '
            "==================== -->\n"
            '<div class="page">\n\n'
            '<div class="runhead">MapleSure Insurance · Enhancement Delivery · '
            f'Stage {stage["num"]} of 5</div>\n\n'
            '<div class="section">\n'
            f'  <h2>Stage {stage["num"]} · {stage["name"]}</h2>\n'
            f'  <p style="margin-bottom:3mm;font-size:12.5pt;color:var(--ink-soft)">'
            f'{stage["lead"]}</p>\n\n'
            + "\n".join(svg) + "\n\n</div>\n\n</div>"
        )
    return "\n\n".join(pages)


def _wrap(text: str, width: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for word in words:
        trial = f"{cur} {word}".strip()
        if len(trial) > width and cur:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines
