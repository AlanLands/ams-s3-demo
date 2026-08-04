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
from s3_enhancement.docshell import (
    Bullets,
    Callout,
    ControlRow,
    Figure,
    Para,
    Part,
    Section,
    Sub,
    Table,
)


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




# --- the QA design document --------------------------------------------------


def _model_blocks(blocks: list[DocBlock], *, missing: str) -> list[docshell.Block]:
    """Turn a bucket of the model's blocks into shell blocks.

    A heading inside a bucket is a *sub*heading: the section's own number came
    from the skeleton, not from the model. An empty bucket becomes a stated gap
    rather than an empty section — the reader has to be able to tell "the model
    said nothing here" apart from "there is nothing to say".
    """
    if not blocks:
        return [Para(docshell.todo(missing))]

    out: list[docshell.Block] = []
    pending: list[list[docshell.Run]] = []

    def flush() -> None:
        if pending:
            out.append(Bullets(list(pending)))
            pending.clear()

    for block in blocks:
        if block.kind == "bullet":
            pending.append(docshell.markup(block.text))
            continue
        flush()
        if block.kind == "heading":
            out.append(Sub(block.text))
        else:
            out.append(Para(docshell.markup(block.text)))
    flush()
    return out


def _file_table(paths: list[str]) -> Table:
    return Table(
        ["#", "File"],
        [
            [docshell.runs(str(i)), docshell.runs(path, code=True)]
            for i, path in enumerate(paths, 1)
        ],
        widths=(8, 92),
    )


def build_design_document(
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
) -> docshell.Document:
    """The QA hand-off document, as the model every renderer draws from."""
    buckets = _split_by_bucket(design_doc)
    stamp = docshell.stamp(today or date.today())
    files = changed_files or []
    source = source or docshell.source_of(files)

    intro = Part(
        "Introduction",
        [
            Section(
                "Purpose of this document",
                [
                    Para(
                        docshell.markup(
                            "This document hands the change described below from engineering "
                            f"to QA. It is generated from the run that produced the change — "
                            f"**{ticket_key}** for user story **{story_label}** — and records "
                            "what was altered, what it reaches, and where testing should "
                            "concentrate."
                        )
                    ),
                    Para(
                        docshell.runs(
                            "It is written before any test has been run. Nothing in it is "
                            "evidence that the change works; that is the release record's job."
                        )
                    ),
                ],
            ),
            Section(
                "Intended audience",
                [
                    Bullets(
                        [
                            docshell.markup(
                                "**The tester** picking the ticket up — sections 3.1 and 3.2 "
                                "are addressed to them."
                            ),
                            docshell.markup(
                                "**The reviewing engineer**, as the record of what was agreed "
                                "at hand-off."
                            ),
                            docshell.markup(
                                "**Whoever supports the application later**, as the account of "
                                "why this change was made."
                            ),
                        ]
                    )
                ],
            ),
            Section(
                "Scope of this change",
                _model_blocks(
                    buckets.get("scope", []),
                    missing="the model returned no summary section for this run.",
                ),
            ),
        ],
    )

    change_sections: list[Section] = []
    if diagram_svg:
        # The caption is not decoration: without it a reader assumes the model
        # drew the diagram, which is the one thing it did not do.
        change_sections.append(
            Section("Change map", [Figure(diagram_svg, diagram_caption)])
        )
    change_sections.append(
        Section(
            "Affected areas",
            _model_blocks(
                buckets.get("affected", []),
                missing="the model returned no affected-areas section for this run.",
            ),
        )
    )
    if files:
        change_sections.append(Section("Files changed", [_file_table(files)]))

    handoff = Part(
        "Hand-off to QA",
        [
            Section(
                "Risk areas",
                _model_blocks(
                    buckets.get("risk", []),
                    missing="the model returned no risk section for this run.",
                ),
            ),
            Section(
                "Suggested QA focus",
                _model_blocks(
                    buckets.get("focus", []),
                    missing="the model returned no QA-focus section for this run.",
                ),
            ),
        ],
    )
    if "extra" in buckets:
        handoff.sections.append(
            Section("Additional notes", _model_blocks(buckets["extra"], missing=""))
        )

    signoff = Part(
        "Sign-off",
        [
            Section(
                "Prepared by",
                [
                    Table(
                        ["Role", "Name", "Date"],
                        [
                            [
                                docshell.runs("Engineer"),
                                docshell.runs(prepared_by or docshell.FILL_MARK),
                                docshell.runs(stamp),
                            ],
                            [
                                docshell.runs("Reviewer"),
                                docshell.runs(docshell.FILL_MARK),
                                docshell.runs(docshell.FILL_MARK),
                            ],
                        ],
                        widths=(24, 46, 30),
                    )
                ],
            ),
            Section(
                "Accepted by QA",
                [
                    Para(
                        docshell.todo(
                            "countersigned by the tester when the ticket is accepted into QA."
                        )
                    ),
                    Table(
                        ["Role", "Name", "Date"],
                        [
                            [
                                docshell.runs("Tester"),
                                docshell.runs(docshell.FILL_MARK),
                                docshell.runs(docshell.FILL_MARK),
                            ]
                        ],
                        widths=(24, 46, 30),
                    ),
                ],
            ),
        ],
    )

    return docshell.Document(
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
            ControlRow("v1.0", stamp, f"Issued at hand-off to QA from run {ticket_key}.")
        ],
        change_note=(
            "Generated per run. Each run issues a fresh version 1.0 — there is no "
            "revision history to carry, because the run that produced the document "
            "is the record."
        ),
        parts=[intro, Part("The change", change_sections), handoff, signoff],
        closing=AI_SUGGESTION_LABEL,
    )


def render_document_html(*args, **kwargs) -> str:
    """The standalone design document, identical for the HTML and PDF exports."""
    return docshell.render_html(build_design_document(*args, **kwargs))


def render_document_docx(*args, **kwargs) -> bytes:
    """The same document as a Word file."""
    from s3_enhancement import docx_export

    return docx_export.render_docx(build_design_document(*args, **kwargs))


# --- the release record ------------------------------------------------------

_STATUS_LABEL = {
    "passed": "Evidenced",
    "failed": "Failing",
    "not_automated": "No automated test",
    "no_scenario": "No scenario",
    "not_run": "Not run",
}


def _steps_table(steps) -> list[docshell.Block]:
    if not steps:
        return [Para(docshell.runs("None."))]
    rows = []
    for step in steps:
        cell = [docshell.Run(step.title, bold=True), docshell.Run("\n" + step.detail)]
        if step.command:
            cell.append(docshell.Run("\n$ " + step.command, code=True))
        rows.append([docshell.runs(str(step.order)), cell])
    return [Table(["#", "Step"], rows, widths=(8, 92))]


def build_release_record(
    record, *, today: date | None = None, source: str = ""
) -> docshell.Document:
    """The release record: what shipped, the evidence, and who signed it.

    Deliberately leads with what shipped and ends with the notes, rather than
    the other way round — the reader who needs this document is checking a
    claim, not reading an announcement. The gaps section sits above the
    approvals so nobody signs without having scrolled past it.

    Sections the run produced nothing for are omitted rather than left empty,
    which is why `docshell` numbers parts at render time: a release with no
    source-control flow and no release notes has to come out with a contiguous
    1-2-3, not with holes where the absent parts would have been.
    """
    stamp = docshell.stamp(today or record.generated_at.date())
    source = source or docshell.source_of(record.changed_files)

    # --- part 1: what shipped -------------------------------------------------
    shipped: list[docshell.Block] = (
        [_file_table(record.changed_files)]
        if record.changed_files
        else [Para(docshell.runs("No files recorded for this release."))]
    )
    summary = Part("Release summary", [Section("What shipped", shipped)])
    if record.diagram_svg:
        summary.sections.append(
            Section("Change map", [Figure(record.diagram_svg, record.diagram_caption)])
        )

    # --- part 2: evidence -----------------------------------------------------
    if record.evidence:
        rows = []
        for item in record.evidence:
            verdict = docshell.runs(
                "PASS" if item.passed else "FAIL", bold=True, tone="ok" if item.passed else "bad"
            )
            counts = f"{item.passed_count}/{item.total}" if item.total else "—"
            rows.append(
                [
                    docshell.runs(item.name),
                    docshell.runs(counts),
                    verdict,
                    docshell.runs(item.note),
                ]
            )
        evidence_blocks: list[docshell.Block] = [
            Table(["Suite", "Passed", "Result", "Note"], rows, widths=(30, 12, 12, 46))
        ]
    else:
        evidence_blocks = [Para(docshell.runs("No test runs were recorded for this release."))]

    evidence = Part("Evidence", [Section("Test evidence", evidence_blocks)])

    if record.matrix is not None:
        rows = []
        for row in record.matrix.rows:
            tone = "ok" if row.status == "passed" else "bad" if row.status == "failed" else ""
            rows.append(
                [
                    [
                        docshell.Run(row.criterion_id, bold=True),
                        docshell.Run("\n" + row.criterion_text),
                    ],
                    docshell.runs(", ".join(row.scenario_ids) or "—"),
                    docshell.runs("\n".join(row.test_names) or "—", code=True),
                    docshell.runs(_STATUS_LABEL.get(row.status, row.status), tone=tone),
                ]
            )
        evidence.sections.append(
            Section(
                "Acceptance criteria",
                [
                    Table(
                        ["Criterion", "Scenarios", "Automated test", "Result"],
                        rows,
                        widths=(42, 14, 30, 14),
                    )
                ],
            )
        )

    if record.unproven:
        evidence.sections.append(
            Section(
                "Not evidenced by this release",
                [
                    Callout(
                        [
                            Para(
                                docshell.runs(
                                    "Everything below is outside what this run proved. It is "
                                    "listed because a release document that only records "
                                    "successes is an advertisement."
                                )
                            ),
                            Bullets([docshell.runs(gap) for gap in record.unproven]),
                        ]
                    )
                ],
            )
        )

    # --- part 3: authorisation ------------------------------------------------
    if record.approvals:
        approvals: list[docshell.Block] = [
            Table(
                ["When", "Action", "Detail"],
                [
                    [
                        docshell.runs(item["ts"]),
                        docshell.runs(item["action"]),
                        docshell.runs(item["detail"]),
                    ]
                    for item in record.approvals
                ],
                widths=(22, 24, 54),
            )
        ]
    else:
        approvals = [
            Para(docshell.runs("No human approvals were recorded against this ticket."))
        ]

    authorisation = Part("Authorisation", [Section("Approvals", approvals)])

    branch = getattr(record, "branch", None)
    if branch is not None:
        rows = [
            [
                docshell.runs("Branch"),
                [
                    docshell.Run(branch.branch, code=True),
                    docshell.Run(" (cut from "),
                    docshell.Run(branch.base, code=True),
                    docshell.Run(")"),
                ],
            ],
            [docshell.runs("Status"), docshell.runs(branch.status)],
        ]
        if branch.commit is not None:
            rows.append(
                [
                    docshell.runs("Commit"),
                    [
                        docshell.Run(branch.commit.sha, code=True),
                        docshell.Run(
                            f" — {branch.commit.message} "
                            f"({len(branch.commit.files)} file(s), "
                            f"{branch.commit.committed_at})"
                        ),
                    ],
                ]
            )
        if branch.pushed_at:
            rows.append(
                [
                    docshell.runs("Pipeline"),
                    docshell.runs(f"{branch.pipeline_id} queued {branch.pushed_at}"),
                ]
            )
        authorisation.sections.append(
            Section(
                "Source control",
                [
                    Table(["Item", "Value"], rows, widths=(22, 78)),
                    # Stated here as well as in the gaps section: a reader who
                    # skims to the branch name and stops must not walk away
                    # thinking git ran.
                    Para(
                        docshell.runs(
                            "Modelled, not executed — this console does not run git or "
                            "contact a remote. See “Not evidenced by this release”."
                        ),
                        note=True,
                    ),
                ],
            )
        )

    # --- part 4: go-live ------------------------------------------------------
    deployment: list[docshell.Block] = []
    if record.plan.order_reason:
        deployment.append(
            Para(docshell.markup(f"**Order matters.** {record.plan.order_reason}"))
        )
    deployment.extend(_steps_table(record.plan.steps))

    golive = Part(
        "Go-live",
        [
            Section("Deployment", deployment),
            Section("Rollback", _steps_table(record.plan.rollback)),
        ],
    )

    parts = [summary, evidence, authorisation, golive]

    # --- part 5: the notes, only when a model produced them --------------------
    if record.notes is not None:
        note_sections = []
        for first, heading, text in (
            (True, "Client change log", record.notes.changelog),
            (False, "Internal operations note", record.notes.ops_note),
            (False, "User guide — what's new", record.notes.whats_new),
        ):
            blocks: list[docshell.Block] = []
            if first:
                blocks.append(
                    Para(
                        docshell.runs("AI-drafted; the rest of this record is computed."),
                        note=True,
                    )
                )
            blocks.append(Para(docshell.markup(text)))
            note_sections.append(Section(heading, blocks))
        parts.append(Part("Release notes", note_sections))

    return docshell.Document(
        kicker="Technical documentation",
        title="Release Record — Ready for Release",
        running_title=f"Release Record ({record.story_label} · {record.ticket_key})",
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
                "v1.0",
                stamp,
                f"Assembled at release of {record.ticket_key} by {record.released_by}.",
            )
        ],
        change_note=(
            "Assembled from what the run produced — the changed files, the test runs, "
            "the ticket's own approval history and the derived deployment plan. Nothing "
            "in it is re-stated from memory."
        ),
        parts=parts,
        closing=AI_SUGGESTION_LABEL,
    )


def render_release_record_html(*args, **kwargs) -> str:
    return docshell.render_html(build_release_record(*args, **kwargs))


def render_release_record_docx(*args, **kwargs) -> bytes:
    from s3_enhancement import docx_export

    return docx_export.render_docx(build_release_record(*args, **kwargs))
