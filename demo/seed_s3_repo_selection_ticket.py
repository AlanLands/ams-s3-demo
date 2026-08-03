"""Demo seed: put AMS-104 on the board — the ticket that makes S3 *choose*
a repo instead of being told which one.

The three standing tickets each carry a user story whose title line is exactly some
registered target's `story_template_path.stem`, so `target_match` resolves them
at tier 1 on an exact structural match and never consults a model. That is
the right default, but it means the repo-selection beat never runs: nothing
on the board is ambiguous.

US-2026-044 is. Its title is no registered target's stem, and its
`Application: PolicyCore` header narrows to *two* targets rather than one
(`targets_for_application` returns both the plan-tier and amendment
targets), so tier 2 declines to guess and falls through to the AI tier. That
is the ambiguity a team owning several repos actually has, and the console
gates checkout/generate on a human accepting whatever the model picked.

Writes the Jira replay caches directly rather than POSTing to the API, so it
needs no running server — and unlike `seed_problem_record_ticket.py` this
ticket must NOT be tagged `origin=problem_record`; it is an ordinary
business user story that simply arrived without naming its target system.

Run after `demo/reset_s3.sh`, which restores `s3_enhancement/cache/jira_*.json`
from HEAD and would otherwise drop this ticket from the board. Idempotent —
re-running it is a no-op once the ticket is present.
"""

from __future__ import annotations

import json
from pathlib import Path

from common import jira_client

KEY = "AMS-104"
# Ravi Kumar already owns AMS-102 and AMS-103, so the board itself shows one
# engineer holding tickets against two different repos — the situation that
# makes "which repo is this one for?" a real question rather than a staged one.
ASSIGNEE = "Ravi Kumar"

ISSUE = {
    "key": KEY,
    "summary": "Flag urgent amendment requests (from Support Ops)",
    "status": "To Do",
    "assignee": ASSIGNEE,
    "issue_type": "Task",
    "description": (
        "Raised on the support floor, not through the change-request desk. "
        "Names the application (PolicyCore) but no target system, so the repo "
        "has to be identified before any work starts. See US-2026-044."
    ),
}

CACHE_ROOT = Path("s3_enhancement") / "cache"


def _seed_get_issue() -> str:
    path = jira_client._cache_path("get_issue", KEY)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"response": ISSUE}, indent=2) + "\n", encoding="utf-8")
    return f"wrote {path}"


def _seed_search_results() -> list[str]:
    """Append the ticket to every seeded board search recording.

    The board is driven by one `search_issues` recording whose filename is a
    hash of the JQL; globbing rather than hardcoding that hash keeps this
    working if the console's query is ever reworded and re-recorded.
    """
    messages = []
    for path in sorted(CACHE_ROOT.glob("jira_search_issues_*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        response = payload.get("response", payload)
        issues = response if isinstance(response, list) else response.get("issues")
        if issues is None:
            continue
        if any(issue.get("key") == KEY for issue in issues):
            messages.append(f"{path.name}: {KEY} already present")
            continue
        issues.append(ISSUE)
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        messages.append(f"{path.name}: added {KEY}")
    return messages


def main() -> None:
    print(_seed_get_issue())
    for message in _seed_search_results():
        print(message)


if __name__ == "__main__":
    main()
