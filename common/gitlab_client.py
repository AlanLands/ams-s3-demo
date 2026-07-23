"""Read-only GitLab REST v4 client for the S3 real-repository demo beat.

This module supports the "connect to your real GitLab" path with narrowly
targeted API calls only: list accessible projects, list repository file paths,
and fetch individual raw files. It never clones a repository and never writes
anything back to GitLab.

`GITLAB_MODE=live|record|replay` mirrors `LLM_MODE` and `HARNESS_MODE` so demo
rehearsals can be recorded and replayed without network access.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

from dotenv import load_dotenv

load_dotenv()

REPO_ROOT = Path(__file__).resolve().parents[1]
_CACHE_ROOT = REPO_ROOT / "s3_enhancement" / "cache"
_TIMEOUT_SECONDS = 10


class GitLabError(Exception):
    """Raised for any GitLab API failure, auth issue, or misconfiguration."""


def _gitlab_mode() -> str:
    mode = os.environ.get("GITLAB_MODE", "live").lower()
    if mode not in {"live", "record", "replay"}:
        raise GitLabError(f"Unknown GITLAB_MODE {mode!r}; expected 'live', 'record', or 'replay'")
    return mode


def _cache_path(call_name: str, key_material: str) -> Path:
    digest = hashlib.sha256(key_material.encode("utf-8")).hexdigest()[:16]
    return _CACHE_ROOT / f"gitlab_{call_name}_{digest}.json"


def _read_cache(path: Path) -> object:
    if not path.exists():
        raise GitLabError(
            f"no GitLab replay recording at {path} — run with GITLAB_MODE=record first"
        )
    return json.loads(path.read_text(encoding="utf-8"))["response"]


def _write_cache(path: Path, call_name: str, args: dict, response: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "call": call_name,
                "args": args,
                "response": response,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _project_url_id(project_id: int | str) -> str:
    return quote(str(project_id), safe="")


def _next_page(headers) -> str | None:
    next_page = headers.get("X-Next-Page")
    if next_page:
        return next_page

    link = headers.get("Link")
    if not link:
        return None
    for part in link.split(","):
        url_part, _, rel_part = part.strip().partition(";")
        if 'rel="next"' not in rel_part:
            continue
        parsed = urlparse(url_part.strip(" <>"))
        query = dict(item.split("=", 1) for item in parsed.query.split("&") if "=" in item)
        return query.get("page")
    return None


class GitLabClient:
    def __init__(self, *, url: str | None = None, token: str | None = None) -> None:
        self.url = (url or os.environ.get("GITLAB_URL", "https://gitlab.com")).rstrip("/")
        self.token = token if token is not None else os.environ.get("GITLAB_TOKEN")

    def list_projects(self) -> list[dict]:
        """List up to 100 membership projects with compact, reviewable fields."""
        call_name = "list_projects"
        args: dict = {}
        path = _cache_path(call_name, self.url)
        mode = _gitlab_mode()
        if mode == "replay":
            response = _read_cache(path)
            if not isinstance(response, list):
                raise GitLabError(f"GitLab replay recording at {path} is not a project list")
            return response

        payload = self._request_json(
            "/api/v4/projects",
            {"membership": "true", "per_page": "100"},
        )
        if not isinstance(payload, list):
            raise GitLabError("GitLab projects response was not a list")

        projects = [self._compact_project(project) for project in payload]
        if mode == "record":
            _write_cache(path, call_name, args, projects)
        return projects

    def list_repo_paths(self, project_id: int | str) -> list[str]:
        """List all blob paths in a project repository tree."""
        call_name = "list_repo_paths"
        args = {"project_id": str(project_id)}
        path = _cache_path(call_name, f"{self.url}|{project_id}")
        mode = _gitlab_mode()
        if mode == "replay":
            response = _read_cache(path)
            if not isinstance(response, list):
                raise GitLabError(f"GitLab replay recording at {path} is not a path list")
            return [str(item) for item in response]

        paths: list[str] = []
        page: str | None = "1"
        while page:
            endpoint = f"/api/v4/projects/{_project_url_id(project_id)}/repository/tree"
            payload, headers = self._request_json_with_headers(
                endpoint,
                {"recursive": "true", "per_page": "100", "page": page},
            )
            if not isinstance(payload, list):
                raise GitLabError("GitLab repository tree response was not a list")
            for entry in payload:
                if isinstance(entry, dict) and entry.get("type") == "blob" and entry.get("path"):
                    paths.append(str(entry["path"]))
            page = _next_page(headers)

        if mode == "record":
            _write_cache(path, call_name, args, paths)
        return paths

    def fetch_files(
        self, project_id: int | str, paths: list[str], ref: str = "main"
    ) -> dict[str, str]:
        """Fetch raw file contents for the requested paths, caching per file."""
        if not paths:
            return {}

        mode = _gitlab_mode()
        results: dict[str, str] = {}
        project_checked = False
        for file_path in paths:
            call_name = "fetch_file"
            args = {"project_id": str(project_id), "ref": ref, "path": file_path}
            cache_path = _cache_path(call_name, f"{project_id}|{ref}|{file_path}")
            if mode == "replay":
                response = _read_cache(cache_path)
                if not isinstance(response, str):
                    raise GitLabError(
                        f"GitLab replay recording at {cache_path} is not file content"
                    )
                results[file_path] = response
                continue

            try:
                content = self._request_text(
                    f"/api/v4/projects/{_project_url_id(project_id)}/repository/files/"
                    f"{quote(file_path, safe='')}/raw",
                    {"ref": ref},
                )
            except GitLabError as exc:
                if self._is_file_not_found(exc):
                    if not project_checked:
                        self._ensure_project_reachable(project_id)
                        project_checked = True
                    continue
                raise

            results[file_path] = content
            if mode == "record":
                _write_cache(cache_path, call_name, args, content)
        return results

    @staticmethod
    def _compact_project(project: object) -> dict:
        if not isinstance(project, dict):
            raise GitLabError("GitLab project entry was not an object")
        compact = {
            "id": project.get("id"),
            "name": project.get("name"),
            "name_with_namespace": project.get("name_with_namespace"),
            "last_activity_at": project.get("last_activity_at"),
        }
        for key in ("web_url", "default_branch", "description"):
            if key in project:
                compact[key] = project.get(key)
        return compact

    @staticmethod
    def _is_file_not_found(exc: GitLabError) -> bool:
        return "HTTP 404" in str(exc)

    def _ensure_project_reachable(self, project_id: int | str) -> None:
        self._request_json(f"/api/v4/projects/{_project_url_id(project_id)}", {})

    def _request_json(self, endpoint: str, params: dict[str, str]) -> object:
        payload, _headers = self._request_json_with_headers(endpoint, params)
        return payload

    def _request_json_with_headers(self, endpoint: str, params: dict[str, str]):
        body, headers = self._request(endpoint, params)
        try:
            return json.loads(body.decode("utf-8")), headers
        except json.JSONDecodeError as exc:
            raise GitLabError(f"GitLab returned invalid JSON for {endpoint}: {exc}") from exc

    def _request_text(self, endpoint: str, params: dict[str, str]) -> str:
        body, _headers = self._request(endpoint, params)
        return body.decode("utf-8")

    def _request(self, endpoint: str, params: dict[str, str]) -> tuple[bytes, object]:
        if not self.token:
            raise GitLabError("GITLAB_TOKEN is required for GITLAB_MODE=live or record")

        query = urlencode(params)
        path = endpoint if endpoint.startswith("/") else f"/{endpoint}"
        request_url = urljoin(self.url + "/", path.lstrip("/"))
        if query:
            request_url = f"{request_url}?{query}"

        request = Request(request_url, headers={"PRIVATE-TOKEN": self.token})
        try:
            with urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
                return response.read(), response.headers
        except HTTPError as exc:
            raise GitLabError(
                f"GitLab API request failed for {endpoint}: HTTP {exc.code} {exc.reason}"
            ) from exc
        except URLError as exc:
            raise GitLabError(f"GitLab API request failed for {endpoint}: {exc.reason}") from exc


_CLIENT: GitLabClient | None = None


def get_client() -> GitLabClient:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = GitLabClient()
    return _CLIENT
