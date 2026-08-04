"""Every user story under `stories/` is a ticket, without anyone seeding one by hand.

The board (`GET /s3/jira/board`) used to know about exactly two kinds of
ticket: the ones in the recorded Jira search, and the ones the console itself
created (cross-team, problem-record) and tracked in the ticket-events log.
Dropping a new `stories/US-YYYY-NNN.md` in did nothing — the demo owner had to
hand-seed a Jira ticket for it first, which is the one manual step the whole
"register a Target, drop its user story under stories/" onboarding story (see
`target_match.py`'s docstring) still had left.

This module is the missing third source. It reads `stories/*.md`, derives a
stable ticket key per user story, and hands the router enough to put a row on the
board. Nothing here calls an LLM, touches Jira, or writes anything — the
router owns those decisions (see `s3.py::_story_board_rows`).

Two things are load-bearing:

**The key is a pure function of the user story identifier**, so the same user story maps to
the same ticket across restarts, resets, and processes — there is nowhere to
persist a counter that would survive `demo/reset_s3.sh`, and a ticket key
that changed between two board loads would strand every event already
recorded against the old one.

**The key lands in a band nothing else uses.** The seeded demo tickets are
AMS-098 and AMS-101..104, and `common/jira_client.py::_synthetic_issue` mints
its replay keys as `AMS-{digest % 900 + 100}` — both live in AMS-100..999.
Derived keys therefore start at AMS-1000, so `US-2026-045` becomes AMS-1045:
readable from the back of the room, and provably not a collision.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
# Looked up at call time, not import time, so a test can point it elsewhere.
STORIES_ROOT = REPO_ROOT / "stories"

# Recorded (actor "system") on the derived key the first time a user story file is
# seen, carrying the user story filename and whatever target it resolved to. The
# router reads it back instead of resolving again — see `_story_link_fields`.
TICKET_CREATED_ACTION = "story_ticket_created"

# See the module docstring: AMS-100..999 is spoken for.
AUTO_KEY_BAND_START = 1000
# Reserved for a user story filename that isn't a `US-YYYY-NNN` identifier at all.
# Disjoint from the readable band above, so a hashed key can never land on a
# sequence-derived one.
FALLBACK_KEY_BAND_START = 10000

_TITLE_RE = re.compile(r"^(US-\d{4}-\d+):[ \t]*(.+?)[ \t]*$", re.MULTILINE)
_STORY_ID_RE = re.compile(r"US-\d{4}-\d+")
_STORY_ID_EXACT_RE = re.compile(r"US-(\d{4})-(\d+)")
_HEADER_RE = re.compile(
    r"^(Requested by|Application|Priority):[ \t]*(.+?)[ \t]*$", re.MULTILINE
)


@dataclass(frozen=True)
class StoryTicket:
    """One user story file, and the board ticket it would open."""

    story_file: str
    story_id: str
    title: str
    key: str
    summary: str
    description: str
    text: str


def ticket_key_for(story_id: str, project_key: str = "AMS") -> str:
    """The ticket key a given user story identifier always maps to.

    Pure — no filesystem, no registry, no counter. Two user stories sharing a sequence
    number across different years (`US-2025-045` and `US-2026-045`) would
    collide; `tests/test_s3_story_intake.py` asserts the user stories actually in `stories/`
    do not, which is the check that catches it rather than a hash that makes
    the keys unreadable to avoid a case that has never occurred.
    """
    match = _STORY_ID_EXACT_RE.fullmatch(story_id)
    if match is None:
        digest = int(hashlib.sha256(story_id.encode("utf-8")).hexdigest(), 16)
        return f"{project_key}-{FALLBACK_KEY_BAND_START + digest % 90000}"
    return f"{project_key}-{AUTO_KEY_BAND_START + int(match.group(2))}"


def story_ids_mentioned(text: str | None) -> set[str]:
    """Every `US-YYYY-NNN` identifier appearing anywhere in `text`."""
    return set(_STORY_ID_RE.findall(text or ""))


def story_ids_on_issue(issue: dict) -> set[str]:
    """Which user stories an existing board ticket already covers.

    Read out of the issue's own summary and description rather than a
    ticket-key -> user story table, for the same reason `target_match.py` refuses to
    keep one: the link is already written down in the ticket text a human
    wrote (`"US-2026-043: Claims Deductible Handling"`, `"... See
    US-2026-044."`), and a second copy of it in code is a thing to keep in
    sync and get wrong.
    """
    return story_ids_mentioned(str(issue.get("summary") or "")) | story_ids_mentioned(
        str(issue.get("description") or "")
    )


def _describe(story_id: str, story_file: str, text: str) -> str:
    """A short ticket description: the user story's own header block, plus where it
    came from. The identifier is repeated here on purpose — it is what
    `story_ids_on_issue` reads back to recognise that this user story already has a
    ticket, and it must survive even if the summary is later edited."""
    headers = [f"{name}: {value}" for name, value in _HEADER_RE.findall(text)]
    lines = [f"Opened automatically from {story_id} (stories/{story_file})."]
    lines.extend(headers)
    return "\n".join(lines)


def parse_story(path: Path, project_key: str = "AMS") -> StoryTicket | None:
    """Parse one `stories/*.md` file, or None if it carries no `US-YYYY-NNN:`
    title line — a README or a draft under `stories/` is not a user story and
    must not become a ticket."""
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    match = _TITLE_RE.search(text)
    if match is None:
        return None
    story_id, title = match.group(1), match.group(2).strip()
    return StoryTicket(
        story_file=path.name,
        story_id=story_id,
        title=title,
        key=ticket_key_for(story_id, project_key),
        # Title only — the board card reads as a user story, not "US-2026-045:
        # ...". The identifier is not lost: `_describe` repeats it in the
        # description, which is the copy `story_ids_on_issue` is documented to
        # read back, and the ticket key (AMS-1045) is still derived from it.
        summary=title,
        description=_describe(story_id, path.name, text),
        text=text,
    )


def all_story_tickets(project_key: str = "AMS") -> list[StoryTicket]:
    """Every user story under `stories/`, oldest identifier first."""
    tickets = [
        ticket
        for ticket in (parse_story(path, project_key) for path in sorted(STORIES_ROOT.glob("*.md")))
        if ticket is not None
    ]
    tickets.sort(key=lambda ticket: ticket.story_id)
    return tickets
