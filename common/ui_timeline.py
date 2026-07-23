"""Streamlit renderer for ticket audit timelines."""

from __future__ import annotations

from html import escape

import streamlit as st

from common.ui_theme import inject_theme

_TIMELINE_CSS = """
<style>
.ams-timeline {
    border-left: 2px solid var(--ams-line);
    margin: 0.5rem 0 0.25rem 0.45rem;
    padding-left: 1rem;
}
.ams-timeline-item {
    position: relative;
    margin: 0 0 0.95rem;
}
.ams-timeline-item::before {
    content: "";
    position: absolute;
    left: -1.39rem;
    top: 0.18rem;
    width: 0.62rem;
    height: 0.62rem;
    border-radius: 50%;
    background: white;
    border: 2px solid var(--ams-accent);
}
.ams-timeline-top {
    display: flex;
    gap: 0.45rem;
    align-items: center;
    flex-wrap: wrap;
}
.ams-timeline-ts {
    color: var(--ams-ink-soft);
    font-size: 0.78rem;
}
.ams-timeline-action {
    color: var(--ams-ink);
    font-weight: 650;
}
.ams-timeline-detail {
    color: var(--ams-ink-soft);
    font-size: 0.88rem;
    margin-top: 0.14rem;
}
.ams-timeline-chip {
    border-radius: 4px;
    font-size: 0.68rem;
    font-weight: 700;
    letter-spacing: 0.03em;
    padding: 0.1rem 0.38rem;
}
.ams-timeline-chip-ai {
    color: var(--ams-accent-ink);
    border: 1px solid var(--ams-accent);
    background: transparent;
}
.ams-timeline-chip-human {
    color: white;
    background: var(--ams-accent);
}
.ams-timeline-chip-system {
    color: var(--ams-ink-soft);
    border: 1px solid var(--ams-line);
    background: transparent;
}
</style>
"""

_ACTOR_LABELS = {
    "ai": "AI",
    "human": "HUMAN APPROVAL",
    "system": "SYSTEM",
}


def _chip(actor: str) -> str:
    label = _ACTOR_LABELS.get(actor, actor.upper())
    actor_class = actor if actor in _ACTOR_LABELS else "system"
    return f'<span class="ams-timeline-chip ams-timeline-chip-{actor_class}">{label}</span>'


def render_timeline(events: list[dict]) -> None:
    """Render a compact vertical timeline for a ticket.

    Every element is built as a single line with no embedded newlines. A
    line that's blank (or whitespace-only) inside a raw HTML block passed to
    `st.markdown(unsafe_allow_html=True)` ends that block per CommonMark's
    HTML-block rule — Streamlit's markdown renderer then treats the
    remainder as regular indented text, which shows up as an escaped,
    monospaced dump instead of rendered HTML. Multi-line indented f-strings
    are exactly how that blank line sneaks in, so this builds one-line
    fragments and joins them with a single space instead.
    """
    inject_theme()
    st.markdown(_TIMELINE_CSS, unsafe_allow_html=True)
    if not events:
        st.caption("No timeline events recorded yet for this ticket.")
        return

    items = []
    for event in events:
        action = str(event.get("action", "")).replace("_", " ").title()
        detail = str(event.get("detail", ""))
        detail_html = (
            f'<div class="ams-timeline-detail">{escape(detail)}</div>' if detail else ""
        )
        items.append(
            '<div class="ams-timeline-item">'
            '<div class="ams-timeline-top">'
            f'{_chip(str(event.get("actor", "system")))}'
            f'<span class="ams-timeline-action">{escape(action)}</span>'
            f'<span class="ams-timeline-ts">{escape(str(event.get("ts", "")))}</span>'
            "</div>"
            f"{detail_html}"
            "</div>"
        )
    st.markdown(
        f'<div class="ams-timeline">{" ".join(items)}</div>',
        unsafe_allow_html=True,
    )
