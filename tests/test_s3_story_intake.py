"""Verifies the user story -> board-ticket derivation behind the board's third
intake source (see s3_enhancement/story_intake.py).

Nothing here calls an LLM, Jira, or the API — this module is pure text and
arithmetic on purpose, and these tests are what pins the two properties the
board depends on: a ticket key that is stable per user story, and a key band that
cannot collide with the seeded demo tickets.
"""

from __future__ import annotations

from s3_enhancement import story_intake

# The hand-seeded demo tickets, from the committed Jira search recording.
# Auto-derived keys must never land on one of these.
SEEDED_DEMO_KEYS = {"AMS-098", "AMS-101", "AMS-102", "AMS-103", "AMS-104"}


def _write_story(root, name: str, body: str):
    root.mkdir(parents=True, exist_ok=True)
    path = root / name
    path.write_text(body, encoding="utf-8")
    return path


def test_ticket_key_is_a_pure_function_of_the_story_id():
    """Nothing persists the user story -> key mapping, so the key has to be
    re-derivable identically after a restart, a reset, or in another
    process."""
    assert story_intake.ticket_key_for("US-2026-045") == "AMS-1045"
    assert story_intake.ticket_key_for("US-2026-045") == story_intake.ticket_key_for("US-2026-045")
    assert story_intake.ticket_key_for("US-2026-045", "OPS") == "OPS-1045"


def test_derived_keys_never_collide_with_the_seeded_demo_tickets():
    """The seeded tickets and jira_client's synthetic replay keys both live in
    AMS-100..999; every derived key must sit above that band."""
    for ticket in story_intake.all_story_tickets():
        assert ticket.key not in SEEDED_DEMO_KEYS
        number = int(ticket.key.rsplit("-", 1)[1])
        assert number >= story_intake.AUTO_KEY_BAND_START


def test_every_committed_story_derives_a_distinct_key():
    """The documented limit of the readable key scheme: two user stories sharing a
    sequence number across different years would map to the same ticket. This
    is the check that catches it, rather than an unreadable hash guarding
    against a case that has never occurred."""
    tickets = story_intake.all_story_tickets()
    assert tickets, "expected the repo's stories/ to hold at least one user story"
    keys = [ticket.key for ticket in tickets]
    assert len(set(keys)) == len(keys)


def test_a_dropped_story_file_becomes_a_ticket(tmp_path, monkeypatch):
    monkeypatch.setattr(story_intake, "STORIES_ROOT", tmp_path / "stories")
    _write_story(
        tmp_path / "stories",
        "US-2027-007.md",
        "US-2027-007: Renewal Notice Channel\n\n"
        "Requested by: MapleSure Product Team\n"
        "Application: PolicyCore (group benefits plan administration portal)\n"
        "Priority: P4 - small enhancement\n\n"
        "Description:\nLet a sponsor choose how renewal notices reach them.\n",
    )

    (ticket,) = story_intake.all_story_tickets()
    assert ticket.key == "AMS-1007"
    assert ticket.story_id == "US-2027-007"
    # Title only: the board card reads as a user story. The identifier lives in
    # the description (asserted below), not the summary.
    assert ticket.summary == "Renewal Notice Channel"
    assert ticket.story_file == "US-2027-007.md"
    # The description carries the user story's own header block and, critically, the
    # identifier — that is what story_ids_on_issue reads back to recognise the
    # user story already has a ticket.
    assert "US-2027-007" in ticket.description
    assert "Requested by: MapleSure Product Team" in ticket.description


def test_markdown_without_a_story_title_is_not_a_ticket(tmp_path, monkeypatch):
    """A README or a half-written note under stories/ is not a user story."""
    monkeypatch.setattr(story_intake, "STORIES_ROOT", tmp_path / "stories")
    _write_story(tmp_path / "stories", "README.md", "# How to write a user story\n\nStart with a title line.\n")

    assert story_intake.all_story_tickets() == []


def test_story_ids_on_issue_reads_summary_and_description():
    """Both shapes the seeded board actually uses: the user story id leading the
    summary (AMS-101..103), and a bare mention in the description
    (AMS-104)."""
    assert story_intake.story_ids_on_issue(
        {"summary": "US-2026-043: Claims Deductible Handling (ClaimsPortal)"}
    ) == {"US-2026-043"}
    assert story_intake.story_ids_on_issue(
        {
            "summary": "Flag urgent amendment requests (from Support Ops)",
            "description": "Names the application but no target system. See US-2026-044.",
        }
    ) == {"US-2026-044"}
    assert story_intake.story_ids_on_issue({"summary": "Quarterly policy data cleanup"}) == set()
    # A ticket whose fields came back null must not raise.
    assert story_intake.story_ids_on_issue({"summary": None, "description": None}) == set()
