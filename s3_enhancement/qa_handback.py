"""Handing a ticket back from QA to the developer who built the change.

The forward leg has existed since the QA hand-off went in: the engineer picks a
tester, assigns them, and moves the ticket to QA. The return leg had nothing —
a tester who found a defect could only say so out loud, because the board's
Reassign dialog renders for a manager and the test stage offered no way to fail
a ticket. The client asked for the round trip on the 2026-08-03 walkthrough.

**Who the ticket goes back to is derived here, from the ticket's own event log,
and never posted by the client.** Same rule as `scm.commit_blockers` and the
release record's approvals: a claim about who is responsible for a piece of
work is read server-side or it is not worth recording. A console that could
name the developer could also name the wrong one, and the audit trail would
have no way to tell.

The rule is "the last person to hold this ticket who is not a tester" rather
than "whoever handed it to QA", because the log records the *actor* of an
assignment as `human`, not by name — the assignee history is the only copy of
who held it. Testers are skipped on the way back so a tester-to-tester hand-off
(a second pair of eyes) does not make a tester the developer.
"""

from __future__ import annotations

from common.roster import is_tester
from s3_enhancement import scm

# Recorded on the ticket when QA hands it back. Distinct from the
# `ticket_assigned` / `ticket_status_changed` events the same action also
# writes: those say where the ticket went, this one says *why*, and the release
# record and the activity feed both want the reason rather than the mechanics.
QA_RETURNED_ACTION = "qa_returned"

# Written by every path that assigns a ticket — the manager's board dialog, the
# QA hand-off, story intake's default, and the hand-back below. Read here as
# the assignee history.
_ASSIGNED_ACTION = "ticket_assigned"


def previous_developer(events: list[dict], *, current_holder: str | None) -> str | None:
    """Who a ticket now sitting with QA goes back to, or None if nobody does.

    Walks the assignee history backwards and returns the first name that is
    neither the current holder nor a tester. None means this ticket has no
    earlier non-tester holder recorded — a ticket a manager assigned straight
    to a tester, or one whose history predates the events log — and the caller
    must refuse rather than guess, because guessing puts someone's name on work
    they never touched.
    """
    for event in reversed(events):
        if event.get("action") != _ASSIGNED_ACTION:
            continue
        name = str(event.get("detail") or "").strip()
        if not name or name == current_holder or is_tester(name):
            continue
        return name
    return None


def return_count(events: list[dict]) -> int:
    """How many times this ticket has already come back from QA.

    Used to number the recorded reason. `record_event` is idempotent per
    (ticket, actor, action, detail), so a second failure reported in the same
    words as the first would otherwise vanish from the timeline — which is
    exactly the ticket you most want a trail for.
    """
    return sum(1 for event in events if event.get("action") == QA_RETURNED_ACTION)


def failure_evidence(events: list[dict]) -> str:
    """The recorded suite failure behind a hand-back, in one line, or "".

    Empty is a real answer and is reported as such: a tester may fail a ticket
    on something no suite covers (wrong wording, a missing case in the plan),
    and the record should say the return rests on their judgement rather than
    imply a red run that never happened.
    """
    summary = scm.evidence_summary(events)
    parts = [
        f"{label} {suite['detail']}".strip()
        for label, suite in (
            ("generated suite:", summary["generated_suite"]),
            ("regression suite:", summary["regression_suite"]),
        )
        if suite is not None and not suite["passed"]
    ]
    return "; ".join(parts)
