"""One-time demo seed: create a ticket tagged origin=problem_record so a
rehearsal can show S3's two intake flavors side by side on the same board —
a direct business CR (AMS-101/102/103) and a ticket derived from a problem
record (repeated incidents -> a permanent-fix problem record -> this
ticket, from the incident-reduction pipeline — a separate workstream, see
CLAUDE.md). Not part of the reset/warm cycle; run once per rehearsal,
against an already-running API server, whenever this second-flavor ticket
should be visible.
"""

from __future__ import annotations

import os

import httpx

API_BASE = os.environ.get("API_BASE", "http://localhost:8000")
LOGIN_NAME = os.environ.get("SEED_LOGIN_NAME", "Ravi Kumar")
LOGIN_PASSCODE = os.environ.get("SEED_LOGIN_PASSCODE", "1001")

SUMMARY = "Recurring nightly batch timeout in BillingGateway"
DESCRIPTION = (
    "Derived from a problem record raised after repeated incidents on the "
    "nightly premium recalculation job — see the incident-reduction "
    "pipeline's problem-record queue for the underlying pattern."
)
PROBLEM_ID = "PRB0012345"


def main() -> None:
    with httpx.Client(base_url=API_BASE, timeout=15.0) as client:
        login = client.post(
            "/api/auth/login", json={"name": LOGIN_NAME, "passcode": LOGIN_PASSCODE}
        )
        login.raise_for_status()

        response = client.post(
            "/api/s3/jira/problem-record-ticket",
            json={
                "summary": SUMMARY,
                "description": DESCRIPTION,
                "problem_id": PROBLEM_ID,
                "assignee": LOGIN_NAME,
            },
        )
        response.raise_for_status()
        issue = response.json()["issue"]
        print(
            f"Created {issue['key']} tagged origin=problem_record "
            f"(problem_id={PROBLEM_ID}), assigned to {LOGIN_NAME}."
        )


if __name__ == "__main__":
    main()
