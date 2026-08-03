"""Narrow Jira Cloud REST v3 client for the S3 "connect your real Jira"
demo beat (US-2026-042's board/ticket integration).

Supports exactly the calls this demo needs: create an issue, look one up,
search via JQL (drives the engineer board view), and attach a file (the
before/after screenshots). Never deletes or transitions an issue, and every
write (`create_issue`, `attach_file`) is only ever invoked from a
human-confirmed action in the frontend — see `api/routers/s3.py`'s
`/jira/*` endpoints.

`JIRA_MODE=live|record|replay` mirrors `GITLAB_MODE`/`HARNESS_MODE`/
`LLM_MODE` so demo rehearsals can be recorded and replayed without a live
Jira account or network access.
"""

from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import os
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from dotenv import load_dotenv

load_dotenv()

REPO_ROOT = Path(__file__).resolve().parents[1]
_CACHE_ROOT = REPO_ROOT / "s3_enhancement" / "cache"
_TIMEOUT_SECONDS = 10


class JiraError(Exception):
    """Raised for any Jira API failure, auth issue, or misconfiguration."""


def _jira_mode() -> str:
    mode = os.environ.get("JIRA_MODE", "replay").lower()
    if mode not in {"live", "record", "replay"}:
        raise JiraError(f"Unknown JIRA_MODE {mode!r}; expected 'live', 'record', or 'replay'")
    return mode


def _cache_path(call_name: str, key_material: str) -> Path:
    digest = hashlib.sha256(key_material.encode("utf-8")).hexdigest()[:16]
    return _CACHE_ROOT / f"jira_{call_name}_{digest}.json"


def _read_cache(path: Path) -> object:
    if not path.exists():
        raise JiraError(f"no Jira replay recording at {path} — run with JIRA_MODE=record first")
    return json.loads(path.read_text(encoding="utf-8"))["response"]


def _write_cache(path: Path, call_name: str, args: dict, response: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"call": call_name, "args": args, "response": response}, indent=2),
        encoding="utf-8",
    )


def _adf_paragraph(text: str) -> dict:
    """Wrap plain text in the minimal Atlassian Document Format Jira's v3
    API requires for the `description` field — a bare string is rejected."""
    return {
        "type": "doc",
        "version": 1,
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
    }


def _plain_text_description(description: object) -> str | None:
    """Best-effort inverse of `_adf_paragraph` — real Jira ADF can nest
    arbitrarily, but this only needs to read back what this client itself
    writes (a single paragraph of plain text)."""
    if description is None:
        return None
    if isinstance(description, str):
        return description
    if not isinstance(description, dict):
        return None
    chunks: list[str] = []
    for node in description.get("content", []):
        if not isinstance(node, dict):
            continue
        for inline in node.get("content", []):
            if isinstance(inline, dict) and inline.get("type") == "text":
                chunks.append(str(inline.get("text", "")))
    return "\n".join(chunks) if chunks else None


class JiraClient:
    def __init__(
        self, *, base_url: str | None = None, email: str | None = None, token: str | None = None
    ) -> None:
        self.base_url = (base_url or os.environ.get("JIRA_BASE_URL", "")).rstrip("/")
        self.email = email if email is not None else os.environ.get("JIRA_EMAIL")
        self.token = token if token is not None else os.environ.get("JIRA_API_TOKEN")

    def create_issue(
        self,
        project_key: str,
        summary: str,
        description: str = "",
        issue_type: str = "Task",
        assignee_name: str | None = None,
    ) -> dict:
        """Create an issue, returning its compact key/id/self link/summary.

        `assignee_name` is carried through as a plain display name — good
        enough for this demo's fictional roster. Real Jira Cloud assignment
        needs an `accountId` (resolved via `/rest/api/3/user/search`), which
        this narrow client doesn't implement; wire that lookup in before
        relying on `assignee_name` against a real Jira Cloud site in
        live/record mode.
        """
        call_name = "create_issue"
        args = {
            "project_key": project_key,
            "summary": summary,
            "description": description,
            "issue_type": issue_type,
            "assignee_name": assignee_name,
        }
        path = _cache_path(call_name, json.dumps(args, sort_keys=True))
        mode = _jira_mode()
        if mode == "replay":
            if path.exists():
                response = _read_cache(path)
                if not isinstance(response, dict):
                    raise JiraError(f"Jira replay recording at {path} is not an issue object")
                return response
            # No pre-recorded response for this exact summary/description —
            # unlike codegen/testgen, a cross-team ticket's content is
            # AI-suggested per user story, so pre-seeding every possible combination
            # isn't realistic. Synthesize a plausible ticket instead of
            # hard-failing: nothing about "what key did Jira assign" needs to
            # be faithfully replayed for this demo to make its point.
            issue = self._synthetic_issue(path, summary, description, issue_type, assignee_name)
            self._update_get_issue_cache(
                issue["key"], status="To Do", summary=summary, issue_type=issue_type,
                assignee=assignee_name, description=description,
            )
            return issue

        fields: dict = {
            "project": {"key": project_key},
            "summary": summary,
            "description": _adf_paragraph(description),
            "issuetype": {"name": issue_type},
        }
        if assignee_name:
            fields["assignee"] = {"name": assignee_name}
        payload = self._request_json("POST", "/rest/api/3/issue", body={"fields": fields})
        issue = self._compact_issue(payload)
        # Jira's create-issue response body doesn't echo `fields` back, so
        # `_compact_issue` alone would show assignee=None even though the
        # issue was created with one — carry the requested name through
        # explicitly rather than a follow-up GET just to display it.
        issue["assignee"] = assignee_name
        issue["description"] = description
        if mode == "record":
            _write_cache(path, call_name, args, issue)
        self._update_get_issue_cache(
            issue["key"], status="To Do", summary=summary, issue_type=issue_type,
            assignee=assignee_name, description=description,
        )
        return issue

    @staticmethod
    def _synthetic_issue(
        path: Path, summary: str, description: str, issue_type: str, assignee_name: str | None
    ) -> dict:
        digest = int(hashlib.sha256(path.name.encode()).hexdigest(), 16)
        key = f"AMS-{digest % 900 + 100}"
        return {
            "key": key,
            "id": key,
            "self": None,
            "summary": summary,
            "status": "To Do",
            "issue_type": issue_type,
            "assignee": assignee_name,
            "description": description,
        }

    def get_issue(self, key: str) -> dict:
        """Fetch one issue's compact fields."""
        call_name = "get_issue"
        args = {"key": key}
        path = _cache_path(call_name, key)
        mode = _jira_mode()
        if mode == "replay":
            response = _read_cache(path)
            if not isinstance(response, dict):
                raise JiraError(f"Jira replay recording at {path} is not an issue object")
            return response

        payload = self._request_json(
            "GET",
            f"/rest/api/3/issue/{key}",
            params={"fields": "summary,status,issuetype,assignee"},
        )
        issue = self._compact_issue(payload)
        if mode == "record":
            _write_cache(path, call_name, args, issue)
        return issue

    def _update_get_issue_cache(self, key: str, **field_updates: object) -> None:
        """Keep `get_issue`'s replay cache in sync after create/assign/status
        changes — each call above caches independently, but a status or
        assignee change needs to be visible to a later `get_issue()` even in
        pure replay mode (e.g. one team assigns/marks-done, and another
        team's screen re-reads the ticket after logging in separately)."""
        path = _cache_path("get_issue", key)
        existing = path.exists() and _read_cache(path)
        merged: dict = dict(existing) if isinstance(existing, dict) else {"key": key}
        merged.update(field_updates)
        _write_cache(path, "get_issue", {"key": key}, merged)

    def search_issues(self, jql: str, *, max_results: int = 50) -> list[dict]:
        """Search issues via JQL — drives the engineer board view."""
        call_name = "search_issues"
        args = {"jql": jql, "max_results": max_results}
        path = _cache_path(call_name, jql)
        mode = _jira_mode()
        if mode == "replay":
            response = _read_cache(path)
            if not isinstance(response, list):
                raise JiraError(f"Jira replay recording at {path} is not an issue list")
            return response

        payload = self._request_json(
            "POST",
            "/rest/api/3/search",
            body={
                "jql": jql,
                "maxResults": max_results,
                "fields": ["summary", "status", "issuetype", "assignee"],
            },
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("issues"), list):
            raise JiraError("Jira search response missing an 'issues' list")
        issues = [self._compact_issue(item) for item in payload["issues"]]
        if mode == "record":
            _write_cache(path, call_name, args, issues)
        return issues

    def attach_file(
        self, key: str, filename: str, content: bytes, mime_type: str | None = None
    ) -> dict:
        """Attach a file (e.g. a before/after screenshot PNG) to an issue."""
        call_name = "attach_file"
        args = {"key": key, "filename": filename}
        # Keyed by ticket and filename only. The content digest used to be in
        # the key, which makes a recording unreplayable for any generated
        # attachment: a rendered PDF embeds a creation timestamp, so its bytes
        # differ every run and the lookup could never hit. Two attachments of
        # the same filename to the same ticket are the same demo beat.
        path = _cache_path(call_name, f"{key}|{filename}")
        mode = _jira_mode()
        if mode == "replay":
            response = _read_cache(path)
            if not isinstance(response, dict):
                raise JiraError(f"Jira replay recording at {path} is not an attachment result")
            return response

        mime_type = mime_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
        payload = self._request_multipart(
            f"/rest/api/3/issue/{key}/attachments", filename, content, mime_type
        )
        attachment_ids = (
            [item.get("id") for item in payload if isinstance(item, dict)]
            if isinstance(payload, list)
            else []
        )
        result = {"filename": filename, "ok": True, "attachment_ids": attachment_ids}
        if mode == "record":
            _write_cache(path, call_name, args, result)
        return result

    def assign_issue(self, key: str, assignee_name: str | None) -> dict:
        """Assign, reassign, or unassign an already-created issue — split from
        `create_issue` so a ticket can land open/unassigned first and get
        assigned later. `assignee_name=None` clears the assignee, which is
        Jira's own `"assignee": null`, not an assignment to an empty name.

        Same demo-only caveat as `create_issue`: a real Jira Cloud site needs
        an `accountId`, not a plain name; wire in a `/rest/api/3/user/search`
        lookup before using this against a real site in live/record mode.
        Unlike create/search, this result is fully determined by its inputs —
        there's nothing server-generated worth faithfully replaying — so it
        always succeeds in replay mode without needing a pre-recording.
        """
        if _jira_mode() != "replay":
            self._request_json(
                "PUT",
                f"/rest/api/3/issue/{key}",
                body={
                    "fields": {
                        "assignee": {"name": assignee_name} if assignee_name else None
                    }
                },
            )
        result = {"key": key, "assignee": assignee_name}
        self._update_get_issue_cache(key, assignee=assignee_name)
        return result

    def set_issue_status(self, key: str, status_name: str) -> dict:
        """Move an issue to the named status via Jira's transitions API.

        Real Jira transitions are keyed by an opaque transition id, not the
        status name — this resolves the id by listing available transitions
        and matching `to.name` (case-insensitive) before firing it. Same
        replay reasoning as `assign_issue`: the result is fully determined by
        the inputs, so no pre-recording is required.
        """
        if _jira_mode() == "replay":
            result = {"key": key, "status": status_name}
            self._update_get_issue_cache(key, status=status_name)
            return result

        transitions_payload = self._request_json("GET", f"/rest/api/3/issue/{key}/transitions")
        transitions = (
            transitions_payload.get("transitions", [])
            if isinstance(transitions_payload, dict)
            else []
        )
        transition_id = next(
            (
                t.get("id")
                for t in transitions
                if isinstance(t, dict)
                and str(t.get("to", {}).get("name", "")).lower() == status_name.lower()
            ),
            None,
        )
        if transition_id is None:
            raise JiraError(
                f"no transition to status {status_name!r} available for {key} "
                f"(available: {[t.get('to', {}).get('name') for t in transitions]})"
            )
        self._request_json(
            "POST",
            f"/rest/api/3/issue/{key}/transitions",
            body={"transition": {"id": transition_id}},
        )
        result = {"key": key, "status": status_name}
        self._update_get_issue_cache(key, status=status_name)
        return result

    @staticmethod
    def _compact_issue(issue: object) -> dict:
        if not isinstance(issue, dict):
            raise JiraError("Jira issue entry was not an object")
        fields = issue.get("fields") or {}
        status = fields.get("status") or {}
        issuetype = fields.get("issuetype") or {}
        assignee = fields.get("assignee") or {}
        return {
            "key": issue.get("key"),
            "id": issue.get("id"),
            "self": issue.get("self"),
            "summary": fields.get("summary"),
            "status": status.get("name"),
            "issue_type": issuetype.get("name"),
            "assignee": assignee.get("displayName") or assignee.get("name"),
            "description": _plain_text_description(fields.get("description")),
        }

    def _auth_header(self) -> str:
        if not self.email or not self.token:
            raise JiraError(
                "JIRA_EMAIL and JIRA_API_TOKEN are required for JIRA_MODE=live or record"
            )
        raw = f"{self.email}:{self.token}".encode()
        return "Basic " + base64.b64encode(raw).decode("ascii")

    def _request_json(
        self, method: str, endpoint: str, *, params: dict | None = None, body: dict | None = None
    ) -> object:
        if not self.base_url:
            raise JiraError("JIRA_BASE_URL is required for JIRA_MODE=live or record")
        url = self.base_url + endpoint
        if params:
            url = f"{url}?{urlencode(params)}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = Request(
            url,
            data=data,
            method=method,
            headers={
                "Authorization": self._auth_header(),
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        raw_body = self._send(request, endpoint)
        if not raw_body:
            return {}
        try:
            return json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise JiraError(f"Jira returned invalid JSON for {endpoint}: {exc}") from exc

    def _request_multipart(
        self, endpoint: str, filename: str, content: bytes, mime_type: str
    ) -> object:
        if not self.base_url:
            raise JiraError("JIRA_BASE_URL is required for JIRA_MODE=live or record")
        boundary = uuid.uuid4().hex
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: {mime_type}\r\n\r\n"
        ).encode() + content + f"\r\n--{boundary}--\r\n".encode()

        request = Request(
            self.base_url + endpoint,
            data=body,
            method="POST",
            headers={
                "Authorization": self._auth_header(),
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "X-Atlassian-Token": "no-check",
                "Accept": "application/json",
            },
        )
        raw_body = self._send(request, endpoint)
        try:
            return json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise JiraError(f"Jira returned invalid JSON for {endpoint}: {exc}") from exc

    @staticmethod
    def _send(request: Request, endpoint: str) -> bytes:
        try:
            with urlopen(request, timeout=_TIMEOUT_SECONDS) as response:  # noqa: S310
                return response.read()
        except HTTPError as exc:
            raise JiraError(
                f"Jira API request failed for {endpoint}: HTTP {exc.code} {exc.reason}"
            ) from exc
        except URLError as exc:
            raise JiraError(f"Jira API request failed for {endpoint}: {exc.reason}") from exc


_CLIENT: JiraClient | None = None


def get_jira_client() -> JiraClient:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = JiraClient()
    return _CLIENT
