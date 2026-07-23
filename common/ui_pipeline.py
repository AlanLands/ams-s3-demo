"""Shared visual pipeline-stepper for multi-stage agent flows (S1, S2).

Renders the sequence of pipeline stages as a connected horizontal stepper —
each stage a status dot (done / active / pending) joined by a connector line
— so an engineer watching an auto-draft or cluster-detail flow can see at a
glance where the pipeline is. Purely presentational: callers track their own
stage statuses (usually just a `[label, status]` list mutated as each step
completes) and pass them in here; this module holds no pipeline logic and no
stage semantics of its own, so it's reusable across S1's incident pipeline
and S2's problem/RCA pipeline without either scenario depending on the other.
"""

from __future__ import annotations

from typing import Literal

import streamlit as st

from common.ui_theme import inject_theme

StageStatus = Literal["done", "active", "pending"]

_STEPPER_CSS = """
<style>
.ams-stepper {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0;
    margin: 0.4rem 0 1.1rem;
}
.ams-stepper-stage {
    display: flex;
    align-items: center;
    gap: 0.4rem;
}
.ams-stepper-dot {
    width: 0.68rem;
    height: 0.68rem;
    border-radius: 50%;
    flex-shrink: 0;
    border: 2px solid var(--ams-line);
    background: white;
}
.ams-stepper-dot-done { border-color: var(--ams-accent); background: var(--ams-accent); }
.ams-stepper-dot-active { border-color: var(--ams-accent); background: white; }
.ams-stepper-dot-pending { border-color: var(--ams-line); background: white; }
.ams-stepper-label {
    font-size: 0.8rem;
    white-space: nowrap;
}
.ams-stepper-label-done { color: var(--ams-ink); font-weight: 600; }
.ams-stepper-label-active { color: var(--ams-accent-ink); font-weight: 700; }
.ams-stepper-label-pending { color: var(--ams-ink-soft); }
.ams-stepper-connector {
    width: 1.4rem;
    height: 2px;
    background: var(--ams-line);
    margin: 0 0.5rem;
    flex-shrink: 0;
}
.ams-stepper-connector-done { background: var(--ams-accent); }
</style>
"""


def render_pipeline_stepper(
    stages: list[tuple[str, StageStatus]],
    container: object = None,
) -> None:
    """Render `stages` (label, status) as a connected horizontal stepper.

    `container` is anything exposing `.markdown(html, unsafe_allow_html=True)`
    — pass an `st.empty()` placeholder to update the same stepper in place as
    a pipeline progresses, or omit it to append a new block via `st`.

    Same one-line-per-fragment HTML construction as
    `ui_timeline.render_timeline`: a blank line inside an `unsafe_allow_html`
    markdown block ends the HTML block early under CommonMark and falls back
    to an escaped text dump, so every fragment here is built and joined
    without embedded newlines.
    """
    inject_theme()
    target = container if container is not None else st
    if not stages:
        return

    parts = [_STEPPER_CSS, '<div class="ams-stepper">']
    for index, (label, status) in enumerate(stages):
        if index > 0:
            prev_status = stages[index - 1][1]
            connector_class = "ams-stepper-connector-done" if prev_status == "done" else ""
            parts.append(f'<div class="ams-stepper-connector {connector_class}"></div>')
        parts.append(
            '<div class="ams-stepper-stage">'
            f'<div class="ams-stepper-dot ams-stepper-dot-{status}"></div>'
            f'<span class="ams-stepper-label ams-stepper-label-{status}">{label}</span>'
            "</div>"
        )
    parts.append("</div>")
    target.markdown(" ".join(parts), unsafe_allow_html=True)


def render_stage_detail(
    title: str,
    *,
    reasoning: str | None = None,
    signals: list[str] | None = None,
    confidence: float | None = None,
    expanded: bool = False,
) -> None:
    """Collapsible per-stage trace detail — the "why" behind a completed
    stepper stage, not just the "what" the stepper's dot already shows.
    Purely presentational, same footing as `render_pipeline_stepper`: it
    only displays whatever reasoning/citation text and confidence a stage's
    own pipeline call already computed (e.g. `quality_gate.assess()`'s
    `.reasoning`/`.score`, `triage.triage()`'s `.ai_reasoning`/`.rule_match`)
    — it never runs any inference of its own.
    """
    inject_theme()
    label = f"{title} — confidence {confidence:.0%}" if confidence is not None else title
    with st.expander(label, expanded=expanded):
        if reasoning:
            st.caption("Reasoning")
            st.write(reasoning)
        if signals:
            st.caption("Signals used")
            for signal in signals:
                st.write(f"- {signal}")
        if not reasoning and not signals:
            st.caption("No additional detail recorded for this stage.")
