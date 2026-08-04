"""The controlled-document model both S3 hand-off documents are built from.

The client's own technical documents open the same way every time: a cover
carrying the document's identity, a table of contents, a document-control
block, then numbered parts and sections. A reader who files one of these knows
where to look before they have read a word of it. Our two hand-off artifacts —
the QA design document and the release record — used to open with a one-line
letterhead and dive straight into prose, which reads as a printout rather than
a document somebody has to keep.

So the shell lives here and the two documents supply parts and sections.

**Sections carry blocks, not HTML.** The first version of this module took
already-rendered HTML for each section body, which was fine while HTML and PDF
were the only outputs — the PDF is the HTML, printed. Word is not: it needs
paragraphs, runs, real table cells and heading *styles*, so a second renderer
reading HTML back out of a string would be a parser, and the two outputs would
drift the first time one of them learned a tag the other did not. `Para`,
`Bullets`, `Table`, `Figure` and `Callout` are the whole vocabulary; each
renderer knows how to draw those five and nothing else.

**Numbering is assigned at render time, not written by the caller.** Both
documents omit whole sections when the run produced nothing for them — a
release with no source-control flow has no source-control section, a release
whose model was unreachable has no release-notes section — and a skeleton with
hard-coded numbers would either leave holes in the sequence or renumber
silently. `Part` and `Section` carry titles; the renderers number whatever they
are handed.

**The HTML contents page links and carries no page numbers.** Chromium
paginates at print time and exposes nothing to compute a page number from, so
any number there would be a guess printed as a fact. The Word export uses a
real TOC field, because Word computes them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from html import escape

ORG = "MapleSure Insurance"
SYSTEM = "AMS Service Console"
CLASSIFICATION = "Internal use only"

TODO_MARK = "[TODO — SME input required]"
FILL_MARK = "[Fill in]"

ACCENT = "8B1E2D"  # the house maroon, as Word wants it: RGB hex, no hash


# --- inline ------------------------------------------------------------------


@dataclass(frozen=True)
class Run:
    """A stretch of text with one look. `\\n` inside `text` is a line break."""

    text: str
    bold: bool = False
    code: bool = False
    tone: str = ""  # "" | "ok" | "bad" | "todo"


Cell = list[Run]

_INLINE_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
_INLINE_SPLIT_RE = re.compile(r"(\*\*.+?\*\*|`[^`]+`)")


def runs(text: str, *, bold: bool = False, code: bool = False, tone: str = "") -> list[Run]:
    """One plain run. The common case, spelled short."""
    return [Run(text, bold=bold, code=code, tone=tone)]


def _code_runs(text: str, *, bold: bool) -> list[Run]:
    out: list[Run] = []
    for piece in re.split(r"(`[^`]+`)", text):
        if not piece:
            continue
        mono = _INLINE_CODE_RE.fullmatch(piece)
        out.append(Run(mono.group(1) if mono else piece, bold=bold, code=bool(mono)))
    return out


def markup(text: str) -> list[Run]:
    """Split the model's loose markdown into runs — `**bold**` and `` `code` ``.

    Code spans nest inside bold, because the model writes its affected-areas
    bullets as ``**`path/to/file.py`**``. A single non-recursive pass turns that
    into one bold run still carrying its backticks, which is invisible in HTML
    review (the old string renderer substituted over the whole line afterwards)
    and very visible in Word.
    """
    out: list[Run] = []
    for piece in _INLINE_SPLIT_RE.split(text):
        if not piece:
            continue
        bold = _INLINE_BOLD_RE.fullmatch(piece)
        if bold:
            out.extend(_code_runs(bold.group(1), bold=True))
            continue
        out.extend(_code_runs(piece, bold=False))
    return out


def todo(reason: str) -> list[Run]:
    """A gap the run cannot fill, marked rather than invented.

    The client's template does this and it is the honest half of a generated
    document: a heading with plausible prose under it reads as fact, a heading
    with this under it reads as an open question.
    """
    return [Run(TODO_MARK, bold=True, tone="todo"), Run(" " + reason)]


# --- blocks ------------------------------------------------------------------


@dataclass(frozen=True)
class Para:
    runs: list[Run]
    note: bool = False  # the italic, muted caveat voice


@dataclass(frozen=True)
class Sub:
    """A subheading inside a section — the model's own headings land here."""

    text: str


@dataclass(frozen=True)
class Bullets:
    items: list[list[Run]]


@dataclass(frozen=True)
class Table:
    headers: list[str]
    rows: list[list[Cell]]
    widths: tuple[int, ...] = ()  # percentages, one per column


@dataclass(frozen=True)
class Figure:
    svg: str
    caption: str = ""


@dataclass(frozen=True)
class Callout:
    blocks: list[Block]


Block = Para | Sub | Bullets | Table | Figure | Callout


# --- document ----------------------------------------------------------------


@dataclass(frozen=True)
class Section:
    title: str
    blocks: list[Block] = field(default_factory=list)


@dataclass(frozen=True)
class Part:
    title: str
    sections: list[Section] = field(default_factory=list)


@dataclass(frozen=True)
class ControlRow:
    version: str
    when: str
    summary: str


@dataclass(frozen=True)
class Document:
    kicker: str
    title: str
    running_title: str
    system_line: str
    meta: list[tuple[str, str]]
    control: list[ControlRow]
    parts: list[Part]
    change_note: str = ""
    closing: str = ""


def numbered(parts: list[Part]):
    """Yield ``(number, part, sections)`` with numbers assigned in order."""
    for index, part in enumerate(parts, start=1):
        subs = [
            (f"{index}.{sub}", section) for sub, section in enumerate(part.sections, start=1)
        ]
        yield f"{index}.0", part, subs


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def anchor(number: str) -> str:
    return "sec-" + _SLUG_RE.sub("-", number.lower()).strip("-")


def stamp(when: date | datetime | None = None) -> str:
    when = when or datetime.now()
    if isinstance(when, datetime):
        return when.strftime("%d %B %Y, %H:%M")
    return when.strftime("%d %B %Y")


def source_of(paths: list[str]) -> str:
    """The repository a set of changed files came from, for the cover's SOURCE row."""
    roots = {"/".join(path.split("/")[:2]) for path in paths if "/" in path}
    if len(roots) == 1:
        return roots.pop()
    return ", ".join(sorted(roots)) if roots else "—"


# --- the HTML renderer -------------------------------------------------------


STYLE = """
  @page { size: A4; margin: 20mm 18mm 20mm; }

  :root {
    --ink: #1f1f1f;
    --ink-soft: #4d4d4d;
    --ink-faint: #7a7a7a;
    --accent: #8b1e2d;
    --line: #d4d4d4;
    --rule: #e6e6e6;
  }

  * { box-sizing: border-box; }

  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Aptos, Calibri,
                 Helvetica, Arial, sans-serif;
    font-size: 10.5pt; line-height: 1.45; color: var(--ink);
    margin: 0 auto; max-width: 174mm; padding: 12mm 0;
    -webkit-print-color-adjust: exact; print-color-adjust: exact;
  }
  @media print { body { max-width: none; padding: 0; } }

  p { margin: 0 0 3mm; }
  ul { margin: 0 0 3mm; padding-left: 5mm; }
  li { margin-bottom: 1.5mm; }
  a { color: var(--ink); text-decoration: none; }

  .page-break { break-before: page; }

  /* ---- cover ---- */
  .cover { padding-top: 6mm; }
  .cover .kicker {
    font-size: 8pt; text-transform: uppercase; letter-spacing: 1.6pt;
    font-weight: 700; color: var(--ink-faint); margin-bottom: 4mm;
  }
  .cover h1 {
    font-size: 26pt; line-height: 1.15; letter-spacing: -0.4pt;
    margin: 0 0 7mm; font-weight: 700;
  }
  .cover .identity { border-left: 3pt solid var(--accent); padding-left: 6mm; }
  .cover .system { font-size: 11pt; color: var(--ink-soft); margin-bottom: 6mm; }
  .cover dl { display: grid; grid-template-columns: 42mm 1fr; gap: 3mm 0; margin: 0; }
  .cover dt {
    font-size: 8pt; text-transform: uppercase; letter-spacing: 1.1pt;
    font-weight: 700; color: var(--ink-faint); padding-top: 0.6mm;
  }
  .cover dd { margin: 0; font-size: 10.5pt; }

  /* ---- headings ---- */
  h2 {
    font-size: 15pt; color: var(--accent); font-weight: 700;
    margin: 9mm 0 3mm; break-after: avoid; letter-spacing: -0.2pt;
  }
  h3 {
    font-size: 12pt; color: var(--accent); font-weight: 700;
    margin: 6mm 0 2.5mm; break-after: avoid;
  }
  h4 {
    font-size: 10.5pt; color: var(--ink); font-weight: 700;
    margin: 4mm 0 2mm; break-after: avoid;
  }

  /* ---- contents ---- */
  .toc { margin-top: 3mm; }
  .toc-entry {
    display: flex; align-items: baseline; gap: 2mm;
    font-size: 10.5pt; margin-bottom: 2mm;
  }
  .toc-entry.part { font-weight: 700; margin-top: 3.5mm; }
  .toc-entry .leader {
    flex: 1; border-bottom: 0.6pt dotted var(--line); transform: translateY(-1mm);
  }
  .toc-note { font-size: 9pt; color: var(--ink-faint); font-style: italic; margin-bottom: 4mm; }

  /* ---- tables ---- */
  table {
    width: 100%; border-collapse: collapse; font-size: 9.5pt;
    margin: 0 0 4mm; break-inside: avoid;
  }
  th {
    background: var(--accent); color: #fff; font-weight: 700; text-align: left;
    padding: 1.8mm 2.2mm; border: 0.75pt solid var(--accent);
  }
  td {
    padding: 1.8mm 2.2mm; border: 0.75pt solid var(--line); vertical-align: top;
  }

  /* ---- inline furniture ---- */
  code, .mono {
    font-family: "SFMono-Regular", Consolas, "Liberation Mono", monospace;
    font-size: 9pt; overflow-wrap: anywhere;
  }
  .todo { color: var(--accent); font-weight: 700; }
  .ok { color: #1c6b3c; font-weight: 700; }
  .bad { color: var(--accent); font-weight: 700; }
  .note { font-size: 9.5pt; color: var(--ink-soft); font-style: italic; margin-bottom: 3mm; }

  figure { margin: 0 0 4mm; break-inside: avoid; }
  figure svg { max-width: 100%; height: auto; }
  figcaption { font-size: 9pt; color: var(--ink-faint); margin-top: 2mm; }

  .callout {
    border: 0.75pt solid var(--line); border-left: 3pt solid var(--accent);
    background: #faf6f7; padding: 3.5mm 4mm; margin: 0 0 4mm; break-inside: avoid;
  }
  .callout ul:last-child, .callout p:last-child { margin-bottom: 0; }

  .step-cmd { display: block; margin-top: 1mm; color: var(--ink-soft); }

  /* Repeated on every printed page by the browser's own print path. The
     server PDF hides these and uses Chromium's header/footer templates
     instead, so the two never both appear — see designdoc.render_pdf. */
  .print-chrome { display: none; }
  @media print {
    .print-chrome {
      display: block; position: fixed; left: 0; right: 0;
      font-size: 8pt; color: var(--ink-faint);
    }
    .print-chrome.head {
      top: -12mm; border-bottom: 0.5pt solid var(--rule); padding-bottom: 1.5mm;
    }
    .print-chrome.foot { bottom: -12mm; border-top: 0.5pt solid var(--rule); padding-top: 1.5mm; }
  }
"""


def _runs_html(items: list[Run]) -> str:
    out: list[str] = []
    for run in items:
        text = escape(run.text).replace("\n", "<br>")
        if run.code:
            text = f"<code>{text}</code>"
        if run.bold:
            text = f"<strong>{text}</strong>"
        if run.tone:
            text = f'<span class="{run.tone}">{text}</span>'
        out.append(text)
    return "".join(out)


def _block_html(block: Block) -> str:
    if isinstance(block, Para):
        css = ' class="note"' if block.note else ""
        return f"<p{css}>{_runs_html(block.runs)}</p>"
    if isinstance(block, Sub):
        return f"<h4>{escape(block.text)}</h4>"
    if isinstance(block, Bullets):
        items = "".join(f"<li>{_runs_html(item)}</li>" for item in block.items)
        return f"<ul>{items}</ul>" if items else ""
    if isinstance(block, Table):
        if not block.rows:
            return ""
        cols = (
            "<colgroup>"
            + "".join(f'<col style="width:{w}%">' for w in block.widths)
            + "</colgroup>"
            if block.widths
            else ""
        )
        head = "".join(f"<th>{escape(text)}</th>" for text in block.headers)
        body = "".join(
            "<tr>" + "".join(f"<td>{_runs_html(cell)}</td>" for cell in row) + "</tr>"
            for row in block.rows
        )
        return f"<table>{cols}<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
    if isinstance(block, Figure):
        caption = f"<figcaption>{escape(block.caption)}</figcaption>" if block.caption else ""
        return f"<figure>{block.svg}{caption}</figure>"
    if isinstance(block, Callout):
        inner = "".join(_block_html(item) for item in block.blocks)
        return f'<div class="callout">{inner}</div>'
    raise TypeError(f"unrenderable block: {block!r}")


def _cover_html(doc: Document) -> str:
    rows = "".join(
        f"<dt>{escape(label)}</dt><dd>{escape(value)}</dd>" for label, value in doc.meta
    )
    return (
        '<section class="cover">'
        f'<div class="kicker">{escape(doc.kicker)}</div>'
        f"<h1>{escape(doc.title)}</h1>"
        '<div class="identity">'
        f'<div class="system">{escape(doc.system_line)}</div>'
        f"<dl>{rows}</dl>"
        "</div></section>"
    )


def _contents_html(doc: Document) -> str:
    entries: list[str] = []
    for number, part, subs in numbered(doc.parts):
        entries.append(
            f'<div class="toc-entry part"><a href="#{anchor(number)}">'
            f"{number} {escape(part.title)}</a><span class=\"leader\"></span></div>"
        )
        for sub_number, section in subs:
            entries.append(
                f'<div class="toc-entry"><a href="#{anchor(sub_number)}">'
                f"{sub_number} {escape(section.title)}</a>"
                '<span class="leader"></span></div>'
            )
    return (
        '<section class="page-break"><h2>Table of Contents</h2>'
        '<p class="toc-note">Entries link to their section. Page numbers are '
        "carried by the Word export, where Word computes them.</p>"
        f'<div class="toc">{"".join(entries)}</div></section>'
    )


def _control_html(doc: Document) -> str:
    rows = [
        [runs(row.version), runs(row.when), runs(row.summary)] for row in doc.control
    ]
    body = _block_html(Table(["Version", "Date", "Summary"], rows, widths=(16, 22, 62)))
    note = f'<p class="note">{escape(doc.change_note)}</p>' if doc.change_note else ""
    return f'<section class="page-break"><h2>Document Control</h2>{note}{body}</section>'


def render_html(doc: Document) -> str:
    """The whole document: cover, contents, document control, numbered parts."""
    body: list[str] = []
    for number, part, subs in numbered(doc.parts):
        body.append(f'<section><h2 id="{anchor(number)}">{number} {escape(part.title)}</h2>')
        for sub_number, section in subs:
            body.append(
                f'<h3 id="{anchor(sub_number)}">{sub_number} {escape(section.title)}</h3>'
            )
            body.extend(_block_html(block) for block in section.blocks)
        body.append("</section>")

    footer = f"{ORG} · {SYSTEM} — {CLASSIFICATION}"
    tail = f'<section><p class="note">{escape(doc.closing)}</p></section>' if doc.closing else ""
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>{escape(doc.title)}</title>
<style>{STYLE}</style></head><body>
<div class="print-chrome head">{escape(doc.running_title)}</div>
<div class="print-chrome foot">{escape(footer)}</div>
{_cover_html(doc)}
{_contents_html(doc)}
{_control_html(doc)}
{"".join(body)}
{tail}
</body></html>
"""
