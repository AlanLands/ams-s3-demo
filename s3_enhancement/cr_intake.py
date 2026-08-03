"""Every CR under `crs/` is a ticket, without anyone seeding one by hand.

The board (`GET /s3/jira/board`) used to know about exactly two kinds of
ticket: the ones in the recorded Jira search, and the ones the console itself
created (cross-team, problem-record) and tracked in the ticket-events log.
Dropping a new `crs/CR-YYYY-NNN.md` in did nothing — the demo owner had to
hand-seed a Jira ticket for it first, which is the one manual step the whole
"register a Target, drop its CR under crs/" onboarding story (see
`target_match.py`'s docstring) still had left.

This module is the missing third source. It reads `crs/*.md`, derives a
stable ticket key per CR, and hands the router enough to put a row on the
board. Nothing here calls an LLM, touches Jira, or writes anything — the
router owns those decisions (see `s3.py::_cr_board_rows`).

Two things are load-bearing:

**The key is a pure function of the CR identifier**, so the same CR maps to
the same ticket across restarts, resets, and processes — there is nowhere to
persist a counter that would survive `demo/reset_s3.sh`, and a ticket key
that changed between two board loads would strand every event already
recorded against the old one.

**The key lands in a band nothing else uses.** The seeded demo tickets are
AMS-098 and AMS-101..104, and `common/jira_client.py::_synthetic_issue` mints
its replay keys as `AMS-{digest % 900 + 100}` — both live in AMS-100..999.
Derived keys therefore start at AMS-1000, so `CR-2026-045` becomes AMS-1045:
readable from the back of the room, and provably not a collision.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
# Looked up at call time, not import time, so a test can point it elsewhere.
CRS_ROOT = REPO_ROOT / "crs"

# Recorded (actor "system") on the derived key the first time a CR file is
# seen, carrying the CR filename and whatever target it resolved to. The
# router reads it back instead of resolving again — see `_cr_link_fields`.
TICKET_CREATED_ACTION = "cr_ticket_created"

# See the module docstring: AMS-100..999 is spoken for.
AUTO_KEY_BAND_START = 1000
# Reserved for a CR filename that isn't a `CR-YYYY-NNN` identifier at all.
# Disjoint from the readable band above, so a hashed key can never land on a
# sequence-derived one.
FALLBACK_KEY_BAND_START = 10000

_TITLE_RE = re.compile(r"^(CR-\d{4}-\d+):[ \t]*(.+?)[ \t]*$", re.MULTILINE)
_CR_ID_RE = re.compile(r"CR-\d{4}-\d+")
_CR_ID_EXACT_RE = re.compile(r"CR-(\d{4})-(\d+)")
_HEADER_RE = re.compile(
    r"^(Requested by|Application|Priority):[ \t]*(.+?)[ \t]*$", re.MULTILINE
)


@dataclass(frozen=True)
class CrTicket:
    """One CR file, and the board ticket it would open."""

    cr_file: str
    cr_id: str
    title: str
    key: str
    summary: str
    description: str
    text: str


def ticket_key_for(cr_id: str, project_key: str = "AMS") -> str:
    """The ticket key a given CR identifier always maps to.

    Pure — no filesystem, no registry, no counter. Two CRs sharing a sequence
    number across different years (`CR-2025-045` and `CR-2026-045`) would
    collide; `tests/test_s3_cr_intake.py` asserts the CRs actually in `crs/`
    do not, which is the check that catches it rather than a hash that makes
    the keys unreadable to avoid a case that has never occurred.
    """
    match = _CR_ID_EXACT_RE.fullmatch(cr_id)
    if match is None:
        digest = int(hashlib.sha256(cr_id.encode("utf-8")).hexdigest(), 16)
        return f"{project_key}-{FALLBACK_KEY_BAND_START + digest % 90000}"
    return f"{project_key}-{AUTO_KEY_BAND_START + int(match.group(2))}"


def cr_ids_mentioned(text: str | None) -> set[str]:
    """Every `CR-YYYY-NNN` identifier appearing anywhere in `text`."""
    return set(_CR_ID_RE.findall(text or ""))


def cr_ids_on_issue(issue: dict) -> set[str]:
    """Which CRs an existing board ticket already covers.

    Read out of the issue's own summary and description rather than a
    ticket-key -> CR table, for the same reason `target_match.py` refuses to
    keep one: the link is already written down in the ticket text a human
    wrote (`"CR-2026-043: Claims Deductible Handling"`, `"... See
    CR-2026-044."`), and a second copy of it in code is a thing to keep in
    sync and get wrong.
    """
    return cr_ids_mentioned(str(issue.get("summary") or "")) | cr_ids_mentioned(
        str(issue.get("description") or "")
    )


def _describe(cr_id: str, cr_file: str, text: str) -> str:
    """A short ticket description: the CR's own header block, plus where it
    came from. The identifier is repeated here on purpose — it is what
    `cr_ids_on_issue` reads back to recognise that this CR already has a
    ticket, and it must survive even if the summary is later edited."""
    headers = [f"{name}: {value}" for name, value in _HEADER_RE.findall(text)]
    lines = [f"Opened automatically from {cr_id} (crs/{cr_file})."]
    lines.extend(headers)
    return "\n".join(lines)


def parse_cr(path: Path, project_key: str = "AMS") -> CrTicket | None:
    """Parse one `crs/*.md` file, or None if it carries no `CR-YYYY-NNN:`
    title line — a README or a draft under `crs/` is not a change request and
    must not become a ticket."""
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    match = _TITLE_RE.search(text)
    if match is None:
        return None
    cr_id, title = match.group(1), match.group(2).strip()
    return CrTicket(
        cr_file=path.name,
        cr_id=cr_id,
        title=title,
        key=ticket_key_for(cr_id, project_key),
        summary=f"{cr_id}: {title}",
        description=_describe(cr_id, path.name, text),
        text=text,
    )


def all_cr_tickets(project_key: str = "AMS") -> list[CrTicket]:
    """Every CR under `crs/`, oldest identifier first."""
    tickets = [
        ticket
        for ticket in (parse_cr(path, project_key) for path in sorted(CRS_ROOT.glob("*.md")))
        if ticket is not None
    ]
    tickets.sort(key=lambda ticket: ticket.cr_id)
    return tickets
