"""Renders S3's hand-off documents as standalone files — HTML or PDF.

Two documents share this module because they share a shell: the QA design
document (engineering → QA, before testing) and the release record
(everything → the ticket, after it). One stylesheet, one cover, one PDF
path, so the two cannot drift into looking like they came from different
systems. The shell itself — cover, contents, document control, numbered parts
— lives in `docshell.py`; this module decides what goes in the sections.

Server-side on purpose. The console used to build the downloadable HTML in the
browser, which was fine while HTML was the only export; adding PDF would have
meant either a second renderer (two stylesheets to keep in step, and they
would not have stayed in step) or shipping the browser's HTML to the server to
be rendered blind. One renderer here produces both, so the PDF is by
construction the same document as the HTML.

The PDF path drives headless Chromium through Playwright, which is already a
pinned dependency of this project (`screenshots.py` uses it for the
before/after capture). It is still treated as optional: a locked-down
environment may have the Python package without the browser binary that
`playwright install` fetches, so a missing browser raises
`PdfUnavailableError` and the console falls back to the browser's own
print-to-PDF rather than the beat dying.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from html import escape

from common.constants import AI_SUGGESTION_LABEL
from s3_enhancement import docshell
from s3_enhancement.docshell import ControlRow, Part, Section


class PdfUnavailableError(Exception):
    """Chromium is not available to render a PDF on this machine."""


@dataclass(frozen=True)
class DocBlock:
    kind: str  # "heading" | "bullet" | "paragraph"
    text: str


_BOLD_HEADING_RE = re.compile(r"^\*\*(.+?)\*\*:?\s*$")
_HASH_HEADING_RE = re.compile(r"^#{1,4}\s+(.*)$")
_NUMBERED_HEADING_RE = re.compile(r"^\d+\.\s+[A-Za-z][A-Za-z /&-]{1,40}:?$")
_BULLET_RE = re.compile(r"^[-*•]\s+")
_INLINE_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
# The model separates its sections with a markdown rule often enough that a
# stray "---" turned up in the rendered document as a paragraph of dashes.
_RULE_RE = re.compile(r"^([-_*])\1{2,}$")


def parse_doc_blocks(text: str) -> list[DocBlock]:
    """Mirror of the console's `parseDocBlocks` — the model writes the design
    doc in loose markdown, and the four shapes it actually emits are a bold
    heading, a hash heading, a numbered section heading, and a bullet."""
    blocks: list[DocBlock] = []
    for raw in text.split("\n"):
        line = raw.strip()
        if not line or _RULE_RE.match(line):
            continue
        bold = _BOLD_HEADING_RE.match(line)
        if bold:
            blocks.append(DocBlock("heading", bold.group(1).rstrip(":")))
            continue
        hashed = _HASH_HEADING_RE.match(line)
        if hashed:
            blocks.append(DocBlock("heading", hashed.group(1)))
            continue
        if _NUMBERED_HEADING_RE.match(line):
            blocks.append(DocBlock("heading", line.rstrip(":")))
            continue
        if _BULLET_RE.match(line):
            blocks.append(DocBlock("bullet", _BULLET_RE.sub("", line)))
            continue
        blocks.append(DocBlock("paragraph", line))
    return blocks


def _inline(value: str) -> str:
    marked = _INLINE_BOLD_RE.sub(r"<strong>\1</strong>", escape(value))
    return _INLINE_CODE_RE.sub(r"<code>\1</code>", marked)


def _blocks_html(blocks: list[DocBlock]) -> str:
    """Render a run of model blocks. Headings inside a section are subheadings —
    the section's own number came from the skeleton, not from the model."""
    out: list[str] = []
    open_list = False
    for block in blocks:
        if block.kind == "bullet" and not open_list:
            out.append("<ul>")
            open_list = True
        elif block.kind != "bullet" and open_list:
            out.append("</ul>")
            open_list = False
        if block.kind == "heading":
            out.append(f"<h4>{_inline(block.text)}</h4>")
        elif block.kind == "bullet":
            out.append(f"<li>{_inline(block.text)}</li>")
        else:
            out.append(f"<p>{_inline(block.text)}</p>")
    if open_list:
        out.append("</ul>")
    return "".join(out)


# The model writes four loose sections (see docgen.build_design_doc_prompt) and
# titles them however it likes. Each bucket is claimed by the first heading that
# matches one of its keywords; anything unclaimed lands in "Additional notes"
# rather than being dropped, because a document that silently discards part of
# what the model wrote is worse than one with an untidy last section.
#
# **The keywords are phrases, not single words, on purpose.** A bare "qa" or
# "change" also matches the document's own title — the model opens with
# "Internal Design Document for QA Handoff" — which claimed the QA-focus bucket
# and pushed the real QA section into "Additional notes". A title cannot match
# any of these.
_BUCKETS: list[tuple[str, tuple[str, ...]]] = [
    ("scope", ("summary", "overview", "scope", "what is changing")),
    ("affected", ("affected", "impacted", "areas touched", "touches")),
    ("risk", ("risk", "caution", "watch out")),
    ("focus", ("qa focus", "suggested qa", "test focus", "testing focus", "coverage")),
]


def _split_by_bucket(design_doc: str) -> dict[str, list[DocBlock]]:
    """Group the model's blocks under the four buckets the prompt asks for."""
    groups: list[tuple[str | None, list[DocBlock]]] = [(None, [])]
    for block in parse_doc_blocks(design_doc):
        if block.kind == "heading":
            groups.append((block.text, []))
        else:
            groups[-1][1].append(block)

    found: dict[str, list[DocBlock]] = {}
    leftovers: list[DocBlock] = []
    for heading, blocks in groups:
        if heading is None:
            leftovers.extend(blocks)
            continue
        lowered = heading.lower()
        for name, keywords in _BUCKETS:
            if name not in found and any(word in lowered for word in keywords):
                found[name] = blocks
                break
        else:
            # A heading with nothing under it is the document's own title, which
            # the shell already supplies — carrying it into "Additional notes"
            # gives the reader a stray subheading and no content.
            if blocks:
                leftovers.append(DocBlock("heading", heading))
                leftovers.extend(blocks)
    if leftovers:
        found["extra"] = leftovers
    return found


def render_document_html(
    design_doc: str,
    *,
    story_label: str,
    ticket_key: str,
    diagram_svg: str | None = None,
    diagram_caption: str = "",
    source: str = "",
    changed_files: list[str] | None = None,
    prepared_by: str = "",
    today: date | None = None,
) -> str:
    """The standalone design document, identical for the HTML and PDF exports."""
    buckets = _split_by_bucket(design_doc)
    stamp = docshell.stamp(today or date.today())
    files = changed_files or []
    source = source or docshell.source_of(files)

    intro = Part(
        "Introduction",
        [
            Section(
                "Purpose of this document",
                docshell.paragraphs(
                    "This document hands the change described below from engineering to "
                    f"QA. It is generated from the run that produced the change — {escape(ticket_key)} "
                    f"for user story {escape(story_label)} — and records what was altered, what it "
                    "reaches, and where testing should concentrate.",
                    "It is written before any test has been run. Nothing in it is evidence "
                    "that the change works; that is the release record's job.",
                ),
            ),
            Section(
                "Intended audience",
                docshell.bullets(
                    [
                        "<strong>The tester</strong> picking the ticket up — sections 3.1 and "
                        "3.2 are addressed to them.",
                        "<strong>The reviewing engineer</strong>, as the record of what was "
                        "agreed at hand-off.",
                        "<strong>Whoever supports the application later</strong>, as the "
                        "account of why this change was made.",
                    ]
                ),
            ),
            Section(
                "Scope of this change",
                _blocks_html(buckets.get("scope", []))
                or f"<p>{docshell.todo('the model returned no summary section for this run.')}</p>",
            ),
        ],
    )

    change_sections = []
    if diagram_svg:
        # The caption is not decoration: without it a reader assumes the model
        # drew the diagram, which is the one thing it did not do.
        caption = (
            f"<figcaption>{escape(diagram_caption)}</figcaption>" if diagram_caption else ""
        )
        change_sections.append(
            Section("Change map", f"<figure>{diagram_svg}{caption}</figure>")
        )
    change_sections.append(
        Section(
            "Affected areas",
            _blocks_html(buckets.get("affected", []))
            or f"<p>{docshell.todo('the model returned no affected-areas section for this run.')}</p>",
        )
    )
    if files:
        change_sections.append(
            Section(
                "Files changed",
                docshell.table(
                    ["#", "File"],
                    [[str(i), f"<code>{escape(path)}</code>"] for i, path in enumerate(files, 1)],
                    widths=["8%", "92%"],
                ),
            )
        )
    change = Part("The change", change_sections)

    handoff = Part(
        "Hand-off to QA",
        [
            Section(
                "Risk areas",
                _blocks_html(buckets.get("risk", []))
                or f"<p>{docshell.todo('the model returned no risk section for this run.')}</p>",
            ),
            Section(
                "Suggested QA focus",
                _blocks_html(buckets.get("focus", []))
                or f"<p>{docshell.todo('the model returned no QA-focus section for this run.')}</p>",
            ),
        ],
    )
    if "extra" in buckets:
        handoff.sections.append(Section("Additional notes", _blocks_html(buckets["extra"])))

    signoff = Part(
        "Sign-off",
        [
            Section(
                "Prepared by",
                docshell.table(
                    ["Role", "Name", "Date"],
                    [
                        [
                            "Engineer",
                            escape(prepared_by) if prepared_by else docshell.FILL_MARK,
                            escape(stamp),
                        ],
                        ["Reviewer", docshell.FILL_MARK, docshell.FILL_MARK],
                    ],
                    widths=["24%", "46%", "30%"],
                ),
            ),
            Section(
                "Accepted by QA",
                f"<p>{docshell.todo('countersigned by the tester when the ticket is accepted into QA.')}</p>"
                + docshell.table(
                    ["Role", "Name", "Date"],
                    [["Tester", docshell.FILL_MARK, docshell.FILL_MARK]],
                    widths=["24%", "46%", "30%"],
                ),
            ),
        ],
    )

    return docshell.render(
        kicker="Technical documentation",
        title="Design Document — Ready for QA",
        running_title=f"Design Document — Ready for QA ({story_label} · {ticket_key})",
        system_line=f"{docshell.ORG} · {docshell.SYSTEM}",
        meta=[
            ("Document ID", f"{ticket_key}-DD"),
            ("User story", story_label),
            ("Version", "v1.0"),
            ("Mode", "Engineering → QA hand-off"),
            ("Source", source),
            ("Generated", stamp),
            ("Classification", docshell.CLASSIFICATION),
        ],
        control=[
            ControlRow("v1.0", stamp, f"Issued at hand-off to QA from run {ticket_key}."),
        ],
        change_note=(
            "Generated per run. Each run issues a fresh version 1.0 — there is no "
            "revision history to carry, because the run that produced the document "
            "is the record."
        ),
        parts=[intro, change, handoff, signoff],
        closing=f'<p class="note">{escape(AI_SUGGESTION_LABEL)}</p>',
    )


_CHROME_CSS = (
    "font-family:-apple-system,'Segoe UI',Helvetica,Arial,sans-serif;"
    "font-size:7.5pt;color:#7a7a7a;width:100%;padding:0 18mm;"
)

_HEADER_TEMPLATE = (
    f'<div style="{_CHROME_CSS}border-bottom:0.5px solid #e6e6e6;padding-bottom:2mm">'
    '<span class="title"></span></div>'
)

# `pageNumber` / `totalPages` are Chromium's own placeholder classes — this is
# the only place a page count is available, which is why the contents page does
# not try to print one.
_FOOTER_TEMPLATE = (
    f'<div style="{_CHROME_CSS}border-top:0.5px solid #e6e6e6;padding-top:2mm;'
    'display:flex;justify-content:space-between">'
    f"<span>{docshell.ORG} · {docshell.SYSTEM} — {docshell.CLASSIFICATION}</span>"
    '<span>Page <span class="pageNumber"></span> of <span class="totalPages"></span></span>'
    "</div>"
)

# The document carries its own fixed header/footer for the browser's print
# path. Chromium's templates do the same job better here (they can count
# pages), so the in-document pair is suppressed for the server PDF — printing
# both would stack two footers on every page.
_SUPPRESS_IN_DOC_CHROME = "<style>.print-chrome{display:none !important}</style>"


def render_pdf(html: str) -> bytes:
    """Print `html` to PDF with headless Chromium.

    Every network request is aborted before the page loads. The document is
    fully self-contained (inline styles, inline SVG, no web fonts), so nothing
    legitimate is blocked — and a renderer that cannot be made to fetch a URL
    cannot be turned into one by whatever ends up in the document body.
    """
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - dependency is pinned
        raise PdfUnavailableError(
            "Playwright is not installed, so the server cannot render a PDF."
        ) from exc

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                page = browser.new_page()
                page.route("**/*", lambda route: route.abort())
                page.set_content(html + _SUPPRESS_IN_DOC_CHROME, wait_until="load")
                return page.pdf(
                    format="A4",
                    print_background=True,
                    display_header_footer=True,
                    header_template=_HEADER_TEMPLATE,
                    footer_template=_FOOTER_TEMPLATE,
                    margin={
                        "top": "22mm",
                        "bottom": "20mm",
                        "left": "18mm",
                        "right": "18mm",
                    },
                )
            finally:
                browser.close()
    except PlaywrightError as exc:
        raise PdfUnavailableError(
            "Chromium is not installed for Playwright on this machine — run "
            "`playwright install chromium`, or use the browser's own "
            "print-to-PDF instead."
        ) from exc


# --- the release record -----------------------------------------------------

_STATUS_LABEL = {
    "passed": "Evidenced",
    "failed": "Failing",
    "not_automated": "No automated test",
    "no_scenario": "No scenario",
    "not_run": "Not run",
}


def _steps_table(steps) -> str:
    if not steps:
        return "<p>None.</p>"
    rows = []
    for step in steps:
        command = (
            f'<code class="step-cmd">$ {escape(step.command)}</code>' if step.command else ""
        )
        rows.append(
            [
                str(step.order),
                f"<strong>{escape(step.title)}</strong><br>{escape(step.detail)}{command}",
            ]
        )
    return docshell.table(["#", "Step"], rows, widths=["8%", "92%"])


def render_release_record_html(record, *, today: date | None = None, source: str = "") -> str:
    """The release record: what shipped, the evidence, and who signed it.

    Deliberately leads with what shipped and ends with the notes, rather than
    the other way round — the reader who needs this document is checking a
    claim, not reading an announcement. The gaps section sits above the
    approvals so nobody signs without having scrolled past it.

    Sections that the run produced nothing for are omitted rather than left
    empty, which is why `docshell` numbers parts at render time: a release with
    no source-control flow and no release notes has to come out with a
    contiguous 1-2-3, not with holes where the absent parts would have been.
    """
    stamp = docshell.stamp(today or record.generated_at.date())
    source = source or docshell.source_of(record.changed_files)

    # --- part 1: what shipped -------------------------------------------------
    if record.changed_files:
        shipped = docshell.table(
            ["#", "File"],
            [
                [str(i), f"<code>{escape(path)}</code>"]
                for i, path in enumerate(record.changed_files, 1)
            ],
            widths=["8%", "92%"],
        )
    else:
        shipped = "<p>No files recorded for this release.</p>"

    summary = Part("Release summary", [Section("What shipped", shipped)])
    if record.diagram_svg:
        caption = (
            f"<figcaption>{escape(record.diagram_caption)}</figcaption>"
            if record.diagram_caption
            else ""
        )
        summary.sections.append(
            Section("Change map", f"<figure>{record.diagram_svg}{caption}</figure>")
        )

    # --- part 2: evidence -----------------------------------------------------
    if record.evidence:
        rows = []
        for item in record.evidence:
            verdict = (
                '<span class="ok">PASS</span>' if item.passed else '<span class="bad">FAIL</span>'
            )
            counts = f"{item.passed_count}/{item.total}" if item.total else "—"
            rows.append([escape(item.name), counts, verdict, escape(item.note)])
        evidence_html = docshell.table(
            ["Suite", "Passed", "Result", "Note"], rows, widths=["30%", "12%", "12%", "46%"]
        )
    else:
        evidence_html = "<p>No test runs were recorded for this release.</p>"

    evidence = Part("Evidence", [Section("Test evidence", evidence_html)])

    if record.matrix is not None:
        rows = []
        for row in record.matrix.rows:
            tests = "<br>".join(escape(name) for name in row.test_names) or "—"
            status = _STATUS_LABEL.get(row.status, row.status)
            css = "ok" if row.status == "passed" else "bad" if row.status == "failed" else ""
            rows.append(
                [
                    f"<strong>{escape(row.criterion_id)}</strong><br>"
                    f"{escape(row.criterion_text)}",
                    escape(", ".join(row.scenario_ids)) or "—",
                    f'<span class="mono">{tests}</span>',
                    f'<span class="{css}">{escape(status)}</span>',
                ]
            )
        evidence.sections.append(
            Section(
                "Acceptance criteria",
                docshell.table(
                    ["Criterion", "Scenarios", "Automated test", "Result"],
                    rows,
                    widths=["42%", "14%", "30%", "14%"],
                ),
            )
        )

    if record.unproven:
        evidence.sections.append(
            Section(
                "Not evidenced by this release",
                '<div class="callout">'
                "<p>Everything below is outside what this run proved. It is listed "
                "because a release document that only records successes is an "
                "advertisement.</p>"
                + docshell.bullets([escape(gap) for gap in record.unproven])
                + "</div>",
            )
        )

    # --- part 3: authorisation ------------------------------------------------
    if record.approvals:
        approvals_html = docshell.table(
            ["When", "Action", "Detail"],
            [
                [escape(item["ts"]), escape(item["action"]), escape(item["detail"])]
                for item in record.approvals
            ],
            widths=["22%", "24%", "54%"],
        )
    else:
        approvals_html = "<p>No human approvals were recorded against this ticket.</p>"

    authorisation = Part("Authorisation", [Section("Approvals", approvals_html)])

    branch = getattr(record, "branch", None)
    if branch is not None:
        rows = [
            [
                "Branch",
                f"<code>{escape(branch.branch)}</code> (cut from "
                f"<code>{escape(branch.base)}</code>)",
            ],
            ["Status", escape(branch.status)],
        ]
        if branch.commit is not None:
            rows.append(
                [
                    "Commit",
                    f"<code>{escape(branch.commit.sha)}</code> — "
                    f"{escape(branch.commit.message)} "
                    f"({len(branch.commit.files)} file(s), {escape(branch.commit.committed_at)})",
                ]
            )
        if branch.pushed_at:
            rows.append(
                ["Pipeline", f"{escape(branch.pipeline_id)} queued {escape(branch.pushed_at)}"]
            )
        authorisation.sections.append(
            Section(
                "Source control",
                docshell.table(["Item", "Value"], rows, widths=["22%", "78%"])
                # Stated here as well as in the gaps section: a reader who skims
                # to the branch name and stops must not walk away thinking git ran.
                + '<p class="note">Modelled, not executed — this console does not run '
                "git or contact a remote. See “Not evidenced by this release”.</p>",
            )
        )

    # --- part 4: go-live ------------------------------------------------------
    order = (
        f"<p><strong>Order matters.</strong> {escape(record.plan.order_reason)}</p>"
        if record.plan.order_reason
        else ""
    )
    golive = Part(
        "Go-live",
        [
            Section("Deployment", order + _steps_table(record.plan.steps)),
            Section("Rollback", _steps_table(record.plan.rollback)),
        ],
    )

    parts = [summary, evidence, authorisation, golive]

    # --- part 5: the notes, only when a model produced them --------------------
    if record.notes is not None:
        parts.append(
            Part(
                "Release notes",
                [
                    Section(
                        heading,
                        '<p class="note">AI-drafted; the rest of this record is computed.</p>'
                        f"<p>{_inline(body)}</p>"
                        if first
                        else f"<p>{_inline(body)}</p>",
                    )
                    for first, heading, body in (
                        (True, "Client change log", record.notes.changelog),
                        (False, "Internal operations note", record.notes.ops_note),
                        (False, "User guide — what's new", record.notes.whats_new),
                    )
                ],
            )
        )

    return docshell.render(
        kicker="Technical documentation",
        title="Release Record — Ready for Release",
        running_title=(
            f"Release Record ({record.story_label} · {record.ticket_key})"
        ),
        system_line=f"{docshell.ORG} · {docshell.SYSTEM}",
        meta=[
            ("Document ID", f"{record.ticket_key}-RR"),
            ("User story", record.story_label),
            ("Version", "v1.0"),
            ("Mode", "Release record"),
            ("Source", source),
            ("Released by", record.released_by),
            ("Generated", stamp),
            ("Classification", docshell.CLASSIFICATION),
        ],
        control=[
            ControlRow(
                "v1.0", stamp, f"Assembled at release of {record.ticket_key} by {record.released_by}."
            ),
        ],
        change_note=(
            "Assembled from what the run produced — the changed files, the test runs, "
            "the ticket's own approval history and the derived deployment plan. Nothing "
            "in it is re-stated from memory."
        ),
        parts=parts,
        closing=f'<p class="note">{escape(AI_SUGGESTION_LABEL)}</p>',
    )
