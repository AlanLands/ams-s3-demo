"""Verifies the CR -> board-ticket derivation behind the board's third
intake source (see s3_enhancement/cr_intake.py).

Nothing here calls an LLM, Jira, or the API — this module is pure text and
arithmetic on purpose, and these tests are what pins the two properties the
board depends on: a ticket key that is stable per CR, and a key band that
cannot collide with the seeded demo tickets.
"""

from __future__ import annotations

from s3_enhancement import cr_intake

# The hand-seeded demo tickets, from the committed Jira search recording.
# Auto-derived keys must never land on one of these.
SEEDED_DEMO_KEYS = {"AMS-098", "AMS-101", "AMS-102", "AMS-103", "AMS-104"}


def _write_cr(root, name: str, body: str):
    root.mkdir(parents=True, exist_ok=True)
    path = root / name
    path.write_text(body, encoding="utf-8")
    return path


def test_ticket_key_is_a_pure_function_of_the_cr_id():
    """Nothing persists the CR -> key mapping, so the key has to be
    re-derivable identically after a restart, a reset, or in another
    process."""
    assert cr_intake.ticket_key_for("CR-2026-045") == "AMS-1045"
    assert cr_intake.ticket_key_for("CR-2026-045") == cr_intake.ticket_key_for("CR-2026-045")
    assert cr_intake.ticket_key_for("CR-2026-045", "OPS") == "OPS-1045"


def test_derived_keys_never_collide_with_the_seeded_demo_tickets():
    """The seeded tickets and jira_client's synthetic replay keys both live in
    AMS-100..999; every derived key must sit above that band."""
    for ticket in cr_intake.all_cr_tickets():
        assert ticket.key not in SEEDED_DEMO_KEYS
        number = int(ticket.key.rsplit("-", 1)[1])
        assert number >= cr_intake.AUTO_KEY_BAND_START


def test_every_committed_cr_derives_a_distinct_key():
    """The documented limit of the readable key scheme: two CRs sharing a
    sequence number across different years would map to the same ticket. This
    is the check that catches it, rather than an unreadable hash guarding
    against a case that has never occurred."""
    tickets = cr_intake.all_cr_tickets()
    assert tickets, "expected the repo's crs/ to hold at least one CR"
    keys = [ticket.key for ticket in tickets]
    assert len(set(keys)) == len(keys)


def test_a_dropped_cr_file_becomes_a_ticket(tmp_path, monkeypatch):
    monkeypatch.setattr(cr_intake, "CRS_ROOT", tmp_path / "crs")
    _write_cr(
        tmp_path / "crs",
        "CR-2027-007.md",
        "CR-2027-007: Renewal Notice Channel\n\n"
        "Requested by: MapleSure Product Team\n"
        "Application: PolicyCore (group benefits plan administration portal)\n"
        "Priority: P4 - small enhancement\n\n"
        "Description:\nLet a sponsor choose how renewal notices reach them.\n",
    )

    (ticket,) = cr_intake.all_cr_tickets()
    assert ticket.key == "AMS-1007"
    assert ticket.cr_id == "CR-2027-007"
    assert ticket.summary == "CR-2027-007: Renewal Notice Channel"
    assert ticket.cr_file == "CR-2027-007.md"
    # The description carries the CR's own header block and, critically, the
    # identifier — that is what cr_ids_on_issue reads back to recognise the
    # CR already has a ticket.
    assert "CR-2027-007" in ticket.description
    assert "Requested by: MapleSure Product Team" in ticket.description


def test_markdown_without_a_cr_title_is_not_a_ticket(tmp_path, monkeypatch):
    """A README or a half-written note under crs/ is not a change request."""
    monkeypatch.setattr(cr_intake, "CRS_ROOT", tmp_path / "crs")
    _write_cr(tmp_path / "crs", "README.md", "# How to write a CR\n\nStart with a title line.\n")

    assert cr_intake.all_cr_tickets() == []


def test_cr_ids_on_issue_reads_summary_and_description():
    """Both shapes the seeded board actually uses: the CR id leading the
    summary (AMS-101..103), and a bare mention in the description
    (AMS-104)."""
    assert cr_intake.cr_ids_on_issue(
        {"summary": "CR-2026-043: Claims Deductible Handling (ClaimsPortal)"}
    ) == {"CR-2026-043"}
    assert cr_intake.cr_ids_on_issue(
        {
            "summary": "Flag urgent amendment requests (from Support Ops)",
            "description": "Names the application but no target system. See CR-2026-044.",
        }
    ) == {"CR-2026-044"}
    assert cr_intake.cr_ids_on_issue({"summary": "Quarterly policy data cleanup"}) == set()
    # A ticket whose fields came back null must not raise.
    assert cr_intake.cr_ids_on_issue({"summary": None, "description": None}) == set()
