"""Verifies s3_enhancement/relevance.py's discover_gitlab_files() funnel:
path-only pre-rank bounds how many files ever get content fetched, and the
result feeds straight into the existing select_relevant_files() unchanged.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from s3_enhancement.relevance import discover_gitlab_files, select_relevant_files


def _fake_client(paths: list[str], contents: dict[str, str]) -> MagicMock:
    client = MagicMock()
    client.list_repo_paths.return_value = paths
    client.fetch_files.side_effect = lambda project_id, shortlist, ref="main": {
        path: contents[path] for path in shortlist if path in contents
    }
    return client


def test_discover_gitlab_files_only_fetches_the_shortlist():
    paths = [f"src/module_{i}.py" for i in range(50)] + ["src/billing_export.py"]
    contents = {path: f"content of {path}" for path in paths}
    client = _fake_client(paths, contents)

    with patch("s3_enhancement.relevance.get_client", return_value=client):
        result = discover_gitlab_files(
            "123", "Add a CSV export for billing records", max_candidates=5
        )

    assert len(result) <= 5
    # fetch_files must never be called with the full 51-path list.
    called_paths = client.fetch_files.call_args.args[1]
    assert len(called_paths) <= 5
    assert "src/billing_export.py" in called_paths


def test_discover_gitlab_files_skips_non_source_paths_before_ranking():
    paths = ["README.md", "package-lock.json", "src/app.py", "node_modules/x/index.js"]
    contents = {"src/app.py": "def handler(): ..."}
    client = _fake_client(paths, contents)

    with patch("s3_enhancement.relevance.get_client", return_value=client):
        discover_gitlab_files("123", "some change", max_candidates=10)

    called_paths = client.fetch_files.call_args.args[1]
    assert called_paths == ["src/app.py"]


def test_discover_gitlab_files_output_feeds_select_relevant_files_directly():
    paths = ["src/billing_export.py", "src/unrelated_thing.py"]
    contents = {
        "src/billing_export.py": "def export_billing_csv(records): return csv",
        "src/unrelated_thing.py": "def totally_unrelated(): pass",
    }
    client = _fake_client(paths, contents)
    cr_text = "Add a CSV export for billing records"

    with patch("s3_enhancement.relevance.get_client", return_value=client):
        gitlab_files = discover_gitlab_files("123", cr_text, max_candidates=10)

    selection = select_relevant_files(cr_text, gitlab_files, core_files=(), design_docs={})
    assert selection.core_files == ()
    assert selection.candidate_pool_size == len(gitlab_files)
