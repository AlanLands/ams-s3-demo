"""Streamlit driver console for S3 Enhancement Delivery."""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pandas as pd
import streamlit as st

from common.constants import AI_SUGGESTION_LABEL, INSURER_NAME
from common.gitlab_client import GitLabError, get_client
from common.llm import LLMError
from common.ui_theme import page_header
from s3_enhancement import relevance
from s3_enhancement.analyze import draft_effort_estimate, draft_impact_analysis
from s3_enhancement.codegen import CodegenResult, generate_change
from s3_enhancement.cr import render_cr, sanitize_tier_name
from s3_enhancement.docgen import draft_release_notes
from s3_enhancement.harness import latest_harness_run
from s3_enhancement.testgen import generate_tests


def render() -> None:
    page_header(
        "S3",
        "Enhancement Delivery",
        "Live CR intake, AI-assisted code generation, generated tests, and release notes.",
    )

    if "s3_tier_name" not in st.session_state:
        st.session_state.s3_tier_name = "Elite"
    st.session_state.setdefault("s3_beat_tokens", {})
    st.session_state.setdefault("s3_beat_tokens_live", {})

    raw_tier = st.text_input("New plan tier name", value=st.session_state.s3_tier_name)
    tier_name, validation_error = sanitize_tier_name(raw_tier)
    if validation_error:
        st.warning(validation_error)
        return
    st.session_state.s3_tier_name = tier_name
    cr_text = render_cr(tier_name)

    st.text_area("CR-2026-041", cr_text, height=240, disabled=True)

    if st.button("Run AI impact analysis"):
        try:
            with st.spinner("Drafting impact analysis and effort estimate..."):
                impact_usage: dict = {}
                effort_usage: dict = {}
                st.session_state.s3_impact = draft_impact_analysis(
                    cr_text, usage_out=impact_usage
                )
                st.session_state.s3_effort = draft_effort_estimate(
                    cr_text, usage_out=effort_usage
                )
            st.session_state.s3_beat_tokens["analysis"] = (
                impact_usage.get("input_tokens", 0)
                + impact_usage.get("output_tokens", 0)
                + effort_usage.get("input_tokens", 0)
                + effort_usage.get("output_tokens", 0)
            )
            st.session_state.s3_beat_tokens_live["analysis"] = bool(
                impact_usage
            ) or bool(effort_usage)
        except LLMError as exc:
            st.caption(f"AI intake analysis unavailable: {exc}")

    if "s3_impact" in st.session_state:
        st.markdown(f"**{AI_SUGGESTION_LABEL}**")
        st.text_area("Impact analysis", st.session_state.s3_impact, height=180)
    if "s3_effort" in st.session_state:
        estimate = st.session_state.s3_effort
        cols = st.columns([1, 1, 3])
        cols[0].metric("Effort", estimate.hours_class)
        cols[1].metric("Priority-equivalent", estimate.priority_equivalent)
        cols[2].write(estimate.reasoning)
    if "s3_impact" in st.session_state or "s3_effort" in st.session_state:
        impact_selection = relevance.select_relevant_files(
            cr_text, relevance.discover_mockapp_files()
        )
        _render_file_selection_panel(impact_selection)
        previous_result = st.session_state.get("s3_codegen_result")
        if previous_result is not None and previous_result.tier_name != tier_name:
            previous_result = None
        _render_token_panel(previous_result)

    if st.button("Generate the change"):
        try:
            with st.spinner("Generating and applying source changes..."):
                result = generate_change(tier_name, cr_text)
            st.session_state.s3_codegen_result = result
            st.session_state.s3_beat_tokens["generate"] = (
                (result.scoped_input_tokens or 0) + (result.scoped_output_tokens or 0)
            )
            st.session_state.s3_beat_tokens_live["generate"] = (
                result.scoped_input_tokens is not None
            )
        except LLMError as exc:
            st.error(f"Code generation failed: {exc}")

    result = st.session_state.get("s3_codegen_result")
    if result is not None:
        stream_box = st.empty()
        streamed = ""
        if result.stream_text_generator is not None:
            for chunk in result.stream_text_generator:
                streamed += chunk
                stream_box.code(streamed, language="json")
        if result.diff_text.strip():
            st.code(result.diff_text, language="diff")
            st.success("The app now has this capability. Open the policy portal tab to try it.")
        else:
            st.info(
                "No changes to apply — the app already has this feature from an earlier "
                "run. Run `demo/reset_s3.sh` to regenerate from a clean baseline."
            )
        codegen_selection = relevance.select_relevant_files(
            cr_text, relevance.discover_mockapp_files()
        )
        _render_file_selection_panel(codegen_selection)
        _render_token_panel(result)
        if os.environ.get("SHOW_DEV_TOOLS", "0") == "1":
            st.caption(f"Replay fallback used: {result.used_replay}")

    if st.button("Generate tests + run"):
        try:
            with st.spinner("Generating tests..."):
                test_result = generate_tests(tier_name, cr_text)
            st.session_state.s3_testgen_result = test_result
            st.session_state.s3_beat_tokens["test"] = (
                (test_result.scoped_input_tokens or 0)
                + (test_result.scoped_output_tokens or 0)
            )
            st.session_state.s3_beat_tokens_live["test"] = (
                test_result.scoped_input_tokens is not None
            )
            st.session_state.s3_pytest_output = _run_pytest()
        except LLMError as exc:
            st.error(f"Test generation failed: {exc}")

    test_result = st.session_state.get("s3_testgen_result")
    if test_result is not None and os.environ.get("SHOW_DEV_TOOLS", "0") == "1":
        st.caption(f"Test replay fallback used: {test_result.used_replay}")
    if "s3_pytest_output" in st.session_state:
        st.code(st.session_state.s3_pytest_output, language="text")

    st.divider()
    st.subheader("Live agent-harness codegen (money-shot beat, runs in a separate terminal)")
    st.caption(
        "Run `demo/run_s3_harness.sh` in a second terminal pane — a real coding-agent CLI "
        "edits mockapp and writes/runs the tests live, on camera. Load the result here for "
        "human review before release notes can be drafted."
    )
    if st.button("Load latest harness run"):
        run_dir = latest_harness_run()
        if run_dir is None or not (run_dir / "status.json").exists():
            st.warning("No harness run found yet — run demo/run_s3_harness.sh first.")
        else:
            st.session_state.s3_harness_status = json.loads(
                (run_dir / "status.json").read_text(encoding="utf-8")
            )
            st.session_state.s3_harness_diff = (run_dir / "diff.patch").read_text(
                encoding="utf-8"
            )
            st.session_state.s3_harness_reviewed = False

    harness_pending = False
    if "s3_harness_status" in st.session_state:
        status = st.session_state.s3_harness_status
        st.markdown(f"**{AI_SUGGESTION_LABEL}**")
        cols = st.columns(3)
        cols[0].metric("Harness", status.get("harness", "-"))
        cols[1].metric("Replay used", str(status.get("used_replay")))
        cols[2].metric("Duration", f"{status.get('duration_s', 0):.1f}s")
        st.code(st.session_state.s3_harness_diff, language="diff")
        st.session_state.s3_harness_reviewed = st.checkbox(
            "I've reviewed this AI-generated change",
            value=st.session_state.get("s3_harness_reviewed", False),
        )
        harness_pending = not st.session_state.s3_harness_reviewed

    if st.button("Draft release notes", disabled=harness_pending):
        try:
            with st.spinner("Drafting release notes..."):
                usage: dict = {}
                st.session_state.s3_release_notes = draft_release_notes(
                    cr_text, usage_out=usage
                )
            st.session_state.s3_beat_tokens["document"] = (
                usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
            )
            st.session_state.s3_beat_tokens_live["document"] = bool(usage)
        except LLMError as exc:
            st.caption(f"AI release notes unavailable: {exc}")
    if harness_pending:
        st.caption("Review and confirm the harness change above before drafting release notes.")

    if "s3_release_notes" in st.session_state:
        st.markdown(f"**{AI_SUGGESTION_LABEL}**")
        st.text_area("Release notes", st.session_state.s3_release_notes, height=180)

    _render_gitlab_panel(cr_text)

    st.divider()
    st.subheader("API usage by beat")
    _render_beat_token_chart()


def _run_pytest() -> str:
    process = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_s3_tier_upgrade.py", "-v"],
        check=False,
        capture_output=True,
        text=True,
    )
    return process.stdout + process.stderr


def _render_file_selection_panel(selection: relevance.SelectionResult) -> None:
    cols = st.columns(2)
    cols[0].metric("Files in this app", selection.candidate_pool_size)
    cols[1].metric("Files used for this change", len(selection.selected))
    by_language = selection.candidate_pool_by_language
    st.caption(f"Candidate pool: {by_language.get('java', 0)} Java")
    screen = selection.subsystem_screen
    if screen.screened_out or screen.in_scope:
        total = len(screen.screened_out) + len(screen.in_scope)
        st.caption(
            f"Design docs consulted: {total} legacy subsystem(s) — "
            f"{len(screen.screened_out)} screened out before any of their source "
            "files were opened for scoring."
        )
        with st.expander("Subsystem design-doc screening"):
            for name in (*screen.in_scope, *screen.screened_out):
                verdict = "in scope" if name in screen.in_scope else "screened out"
                st.write(f"{name}: {verdict} (score {screen.scores.get(name, 0.0):.4f})")
    with st.expander("Selected source files"):
        for rel_path in selection.selected:
            st.write(rel_path)
        if os.environ.get("SHOW_DEV_TOOLS", "0") == "1":
            st.caption("Top-scored candidates")
            for rel_path, score in sorted(
                selection.scores.items(),
                key=lambda item: (item[1], item[0]),
                reverse=True,
            )[:10]:
                st.write(f"{rel_path}: {score:.4f}")


def _render_token_panel(result: CodegenResult | None) -> None:
    estimate = st.session_state.get("s3_effort")
    if result is None or result.scoped_input_tokens is None:
        st.caption("Token count unavailable for this run.")
    elif result.naive_input_tokens_estimate > 0:
        scoped = result.scoped_input_tokens
        naive = result.naive_input_tokens_estimate
        ratio = naive / max(scoped, 1)
        if ratio < 1.05:
            # Scoping kept (nearly) every file, so there was nothing to save.
            # Flooring the multiplier at 1 rendered this as "1x fewer".
            st.caption(
                f"Scoped context used {scoped:,} input tokens - no saving over "
                "whole-app context here, since this change needed essentially "
                "every file in the app."
            )
        else:
            multiplier = f"{ratio:.1f}" if ratio < 10 else str(round(ratio))
            st.caption(
                f"Scoped context used {scoped:,} input tokens; a whole-app-context "
                f"approach would have used ~{naive:,} tokens - {multiplier}x more."
            )
    else:
        st.caption("Naive whole-app token estimate unavailable for this run.")
    if estimate is not None:
        st.caption(
            f"An engineer would estimate {estimate.hours_class} for a change like this."
        )


def _render_gitlab_panel(cr_text: str) -> None:
    st.divider()
    st.subheader("Connect your GitLab")
    st.caption(
        "Proves this scales to your real GitLab org, not just the MapleSure demo app — "
        "read-only, and only ever scopes down to a handful of files per repo before "
        "anything reaches an LLM prompt, no matter how many repos or how large any one "
        "of them is. Does not write anything back to GitLab."
    )

    if st.button("List my GitLab repos"):
        try:
            st.session_state.s3_gitlab_projects = get_client().list_projects()
        except GitLabError as exc:
            st.error(f"Could not reach GitLab: {exc}")

    projects = st.session_state.get("s3_gitlab_projects")
    if not projects:
        st.caption('Click "List my GitLab repos" to connect (uses GITLAB_MODE from .env).')
        return

    st.dataframe(
        [
            {
                "name": project.get("name_with_namespace", project.get("name")),
                "last_activity": project.get("last_activity_at"),
            }
            for project in projects
        ],
        use_container_width=True,
        hide_index=True,
    )

    labels = [
        f'{project.get("name_with_namespace", project.get("name"))} (#{project.get("id")})'
        for project in projects
    ]
    chosen_label = st.selectbox("Target repo for this CR", labels)
    chosen = projects[labels.index(chosen_label)]

    if st.button("Scope files for this repo"):
        try:
            with st.spinner("Listing repo files and scoping the relevant ones..."):
                repo_size = len(get_client().list_repo_paths(chosen["id"]))
                gitlab_files = relevance.discover_gitlab_files(chosen["id"], cr_text)
                selection = relevance.select_relevant_files(
                    cr_text, gitlab_files, core_files=(), design_docs={}
                )
            st.session_state.s3_gitlab_repo_size = repo_size
            st.session_state.s3_gitlab_selection = selection
        except GitLabError as exc:
            st.error(f"GitLab scoping failed: {exc}")

    selection = st.session_state.get("s3_gitlab_selection")
    if selection is None:
        return

    repo_size = st.session_state.get("s3_gitlab_repo_size", selection.candidate_pool_size)
    cols = st.columns(2)
    cols[0].metric("Files in this repo", repo_size)
    cols[1].metric("Files that reached the LLM", len(selection.selected))
    st.caption(
        f"Only {len(selection.selected)} of {repo_size} files were ever fetched and scored "
        "for this change — the rest of the repo, and every other repo in your org, was "
        "never read."
    )
    with st.expander("Files sent to the LLM"):
        for rel_path in selection.selected:
            st.write(rel_path)


def _render_beat_token_chart() -> None:
    tokens = st.session_state.get("s3_beat_tokens", {})
    if not tokens:
        return
    order = ["analysis", "generate", "test", "document"]
    ordered = {label: tokens[label] for label in order if label in tokens}
    st.bar_chart(pd.DataFrame.from_dict(ordered, orient="index", columns=["tokens"]))
    st.caption("Total tokens (input + output) used by each AI call type in this run.")
    cached_beats = [
        label
        for label in ordered
        if not st.session_state.get("s3_beat_tokens_live", {}).get(label, True)
    ]
    if cached_beats:
        st.caption(
            "No live usage available for: "
            + ", ".join(cached_beats)
            + " (served from cache/replay this run)."
        )


if __name__ == "__main__":
    st.set_page_config(page_title=f"{INSURER_NAME} - S3 Enhancement Delivery", layout="wide")
    render()
