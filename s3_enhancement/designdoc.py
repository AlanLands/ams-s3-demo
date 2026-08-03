"""Renders S3's hand-off documents as standalone files — HTML or PDF.

Two documents share this module because they share a shell: the QA design
document (engineering → QA, before testing) and the release record
(everything → the ticket, after it). One stylesheet, one letterhead, one PDF
path, so the two cannot drift into looking like they came from different
systems.

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


def parse_doc_blocks(text: str) -> list[DocBlock]:
    """Mirror of the console's `parseDocBlocks` — the model writes the design
    doc in loose markdown, and the four shapes it actually emits are a bold
    heading, a hash heading, a numbered section heading, and a bullet."""
    blocks: list[DocBlock] = []
    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
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
    return _INLINE_BOLD_RE.sub(r"<strong>\1</strong>", escape(value))


_STYLE = """
  @page { size: A4; margin: 18mm 16mm; }
  body { font-family: Georgia, 'Times New Roman', serif; max-width: 760px;
         margin: 3rem auto; padding: 0 1.5rem; color: #1e293b; line-height: 1.55; }
  .letterhead { display: flex; justify-content: space-between; align-items: baseline;
                border-bottom: 3px double #94a3b8; padding-bottom: .6rem; }
  .letterhead .org { font-size: 1.15rem; font-weight: 700; letter-spacing: .02em; }
  .letterhead .kind { font-size: .8rem; color: #64748b; text-transform: uppercase;
                      letter-spacing: .1em; }
  .meta { font-size: .85rem; color: #475569; margin: .8rem 0 1.6rem; }
  h2 { font-size: 1.05rem; margin: 1.4rem 0 .4rem; border-bottom: 1px solid #e2e8f0;
       padding-bottom: .2rem; }
  figure { margin: 1.4rem 0; page-break-inside: avoid; break-inside: avoid; }
  figure svg { max-width: 100%; height: auto; }
  figcaption { font-size: .78rem; color: #64748b; margin-top: .5rem; }
  .label { margin-top: 2.2rem; font-size: .75rem; color: #64748b;
           border-top: 1px solid #e2e8f0; padding-top: .6rem; }
  table { width: 100%; border-collapse: collapse; font-size: .82rem; margin: .6rem 0 1rem; }
  th { text-align: left; font-size: .7rem; text-transform: uppercase; letter-spacing: .06em;
       color: #64748b; border-bottom: 1px solid #cbd5e1; padding: .3rem .4rem; }
  td { padding: .35rem .4rem; border-bottom: 1px solid #eef2f6; vertical-align: top; }
  code, .mono { font-family: 'SFMono-Regular', Consolas, monospace; font-size: .78rem;
                overflow-wrap: anywhere; }
  .ok { color: #0f766e; font-weight: 700; }
  .bad { color: #b91c1c; font-weight: 700; }
  .gaps { border: 1px solid #e2c391; background: #fdf6e7; border-radius: 4px;
          padding: .7rem .9rem; margin: 1rem 0; }
  .gaps h3 { font-size: .82rem; margin: 0 0 .4rem; text-transform: uppercase;
             letter-spacing: .06em; color: #92610a; }
  .gaps ul { margin: 0; padding-left: 1.1rem; }
  .drafted { font-size: .72rem; color: #64748b; font-style: italic; }
  .step-cmd { display: block; margin-top: .2rem; color: #334155; }
  @media print { body { margin: 0; max-width: none; } }
"""



def render_document_html(
    design_doc: str,
    *,
    story_label: str,
    ticket_key: str,
    diagram_svg: str | None = None,
    diagram_caption: str = "",
    today: date | None = None,
) -> str:
    """The standalone design document, identical for the HTML and PDF exports."""
    body: list[str] = []
    open_list = False
    for block in parse_doc_blocks(design_doc):
        if block.kind == "bullet" and not open_list:
            body.append("<ul>")
            open_list = True
        elif block.kind != "bullet" and open_list:
            body.append("</ul>")
            open_list = False
        if block.kind == "heading":
            body.append(f"<h2>{_inline(block.text)}</h2>")
        elif block.kind == "bullet":
            body.append(f"<li>{_inline(block.text)}</li>")
        else:
            body.append(f"<p>{_inline(block.text)}</p>")
    if open_list:
        body.append("</ul>")

    figure = ""
    if diagram_svg:
        # The caption is not decoration: without it a reader assumes the model
        # drew the diagram, which is the one thing it did not do.
        caption = (
            f"<figcaption>{escape(diagram_caption)}</figcaption>" if diagram_caption else ""
        )
        figure = (
            '<figure><h2 style="border:none;padding:0;margin-bottom:.6rem">Change map</h2>'
            f"{diagram_svg}{caption}</figure>"
        )

    stamp = (today or date.today()).strftime("%d %B %Y")
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>{escape(story_label)} — Design Document</title>
<style>{_STYLE}</style></head><body>
<div class="letterhead"><span class="org">MapleSure Insurance</span>\
<span class="kind">Internal Design Document</span></div>
<div class="meta">{escape(story_label)} · Ticket {escape(ticket_key)} · {stamp} · \
Engineering → QA hand-off</div>
{figure}
{chr(10).join(body)}
<div class="label">{escape(AI_SUGGESTION_LABEL)}</div>
</body></html>
"""


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
                page.set_content(html, wait_until="load")
                return page.pdf(
                    format="A4",
                    print_background=True,
                    margin={
                        "top": "18mm",
                        "bottom": "18mm",
                        "left": "16mm",
                        "right": "16mm",
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
            f"<tr><td>{step.order}</td><td><strong>{escape(step.title)}</strong><br>"
            f"{escape(step.detail)}{command}</td></tr>"
        )
    return f"<table><tbody>{''.join(rows)}</tbody></table>"


def render_release_record_html(record, *, today: date | None = None) -> str:
    """The release record: what shipped, the evidence, and who signed it.

    Deliberately leads with what shipped and ends with the notes, rather than
    the other way round — the reader who needs this document is checking a
    claim, not reading an announcement. The gaps block sits above the
    approvals so nobody signs without having scrolled past it.
    """
    sections: list[str] = []

    sections.append("<h2>What shipped</h2>")
    if record.changed_files:
        rows = "".join(
            f'<tr><td><code>{escape(path)}</code></td></tr>' for path in record.changed_files
        )
        sections.append(f"<table><tbody>{rows}</tbody></table>")
    else:
        sections.append("<p>No files recorded for this release.</p>")

    if record.diagram_svg:
        caption = (
            f"<figcaption>{escape(record.diagram_caption)}</figcaption>"
            if record.diagram_caption
            else ""
        )
        sections.append(f"<figure>{record.diagram_svg}{caption}</figure>")

    sections.append("<h2>Test evidence</h2>")
    if record.evidence:
        rows = []
        for item in record.evidence:
            verdict = (
                '<span class="ok">PASS</span>' if item.passed else '<span class="bad">FAIL</span>'
            )
            counts = f"{item.passed_count}/{item.total}" if item.total else "—"
            rows.append(
                f"<tr><td>{escape(item.name)}</td><td>{counts}</td><td>{verdict}</td>"
                f"<td>{escape(item.note)}</td></tr>"
            )
        sections.append(
            "<table><thead><tr><th>Suite</th><th>Passed</th><th>Result</th><th>Note</th>"
            f"</tr></thead><tbody>{''.join(rows)}</tbody></table>"
        )
    else:
        sections.append("<p>No test runs were recorded for this release.</p>")

    if record.matrix is not None:
        sections.append("<h2>Acceptance criteria</h2>")
        rows = []
        for row in record.matrix.rows:
            tests = "<br>".join(escape(name) for name in row.test_names) or "—"
            status = _STATUS_LABEL.get(row.status, row.status)
            css = "ok" if row.status == "passed" else "bad" if row.status == "failed" else ""
            rows.append(
                f"<tr><td><strong>{escape(row.criterion_id)}</strong><br>"
                f"{escape(row.criterion_text)}</td>"
                f"<td>{escape(', '.join(row.scenario_ids)) or '—'}</td>"
                f'<td class="mono">{tests}</td>'
                f'<td class="{css}">{escape(status)}</td></tr>'
            )
        sections.append(
            '<table style="table-layout:fixed"><colgroup><col style="width:42%">'
            '<col style="width:14%"><col style="width:30%"><col style="width:14%"></colgroup>'
            "<thead><tr><th>Criterion</th><th>Scenarios</th><th>Automated test</th>"
            f"<th>Result</th></tr></thead><tbody>{''.join(rows)}</tbody></table>"
        )

    if record.unproven:
        items = "".join(f"<li>{escape(gap)}</li>" for gap in record.unproven)
        sections.append(
            '<div class="gaps"><h3>Not evidenced by this release</h3>'
            f"<ul>{items}</ul></div>"
        )

    sections.append("<h2>Approvals</h2>")
    if record.approvals:
        rows = "".join(
            f"<tr><td>{escape(item['ts'])}</td><td>{escape(item['action'])}</td>"
            f"<td>{escape(item['detail'])}</td></tr>"
            for item in record.approvals
        )
        sections.append(
            "<table><thead><tr><th>When</th><th>Action</th><th>Detail</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>"
        )
    else:
        sections.append("<p>No human approvals were recorded against this ticket.</p>")

    branch = getattr(record, "branch", None)
    if branch is not None:
        sections.append("<h2>Source control</h2>")
        rows = [
            ("Branch", f"<code>{escape(branch.branch)}</code> (cut from "
                       f"<code>{escape(branch.base)}</code>)"),
            ("Status", escape(branch.status)),
        ]
        if branch.commit is not None:
            rows.append(
                (
                    "Commit",
                    f"<code>{escape(branch.commit.sha)}</code> — "
                    f"{escape(branch.commit.message)} "
                    f"({len(branch.commit.files)} file(s), {escape(branch.commit.committed_at)})",
                )
            )
        if branch.pushed_at:
            rows.append(
                ("Pipeline", f"{escape(branch.pipeline_id)} queued {escape(branch.pushed_at)}")
            )
        body = "".join(
            f"<tr><td><strong>{label}</strong></td><td>{value}</td></tr>"
            for label, value in rows
        )
        sections.append(f"<table><tbody>{body}</tbody></table>")
        # Stated here as well as in the gaps block: a reader who skims to the
        # branch name and stops must not walk away thinking git ran.
        sections.append(
            '<p class="drafted">Modelled, not executed — this console does not run '
            "git or contact a remote. See “Not evidenced by this release”.</p>"
        )

    sections.append("<h2>Deployment</h2>")
    if record.plan.order_reason:
        sections.append(
            f"<p><strong>Order matters.</strong> {escape(record.plan.order_reason)}</p>"
        )
    sections.append(_steps_table(record.plan.steps))
    sections.append("<h2>Rollback</h2>")
    sections.append(_steps_table(record.plan.rollback))

    if record.notes is not None:
        sections.append("<h2>Release notes</h2>")
        sections.append('<p class="drafted">AI-drafted; the rest of this record is computed.</p>')
        for heading, body in (
            ("Client change log", record.notes.changelog),
            ("Internal operations note", record.notes.ops_note),
            ("User guide — what's new", record.notes.whats_new),
        ):
            sections.append(f"<h3 style=\"font-size:.9rem;margin:.9rem 0 .2rem\">{heading}</h3>")
            sections.append(f"<p>{_inline(body)}</p>")

    stamp = (today or record.generated_at.date()).strftime("%d %B %Y")
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>{escape(record.story_label)} — Release Record</title>
<style>{_STYLE}</style></head><body>
<div class="letterhead"><span class="org">MapleSure Insurance</span>\
<span class="kind">Release Record</span></div>
<div class="meta">{escape(record.story_label)} · Ticket {escape(record.ticket_key)} · {stamp} · \
Released by {escape(record.released_by)}</div>
{chr(10).join(sections)}
<div class="label">{escape(AI_SUGGESTION_LABEL)}</div>
</body></html>
"""
