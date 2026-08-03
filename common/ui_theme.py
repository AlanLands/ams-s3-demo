"""Shared visual theme for every scenario's Streamlit view.

Centralizes the "MapleSure Insurance AMS Console" look so all six scenarios
and the unified nav (`demo/unified_app.py`) render as one consistent product
instead of six differently-styled prototypes. Palette is inspired by a
mainstream Canadian BFSI institutional look (deep maroon/teal, warm
off-white, sharp/zero-radius controls) — colors and type only, never a real
brand name, logo, or asset (see CLAUDE.md: no real client name or branding
anywhere in this repo).

Base colors live in `.streamlit/config.toml` (Streamlit's own theming system);
this module adds the CSS that config alone can't reach — the page header
banner and small typography/spacing touches. Every `render()`/`main()` across
S1-S6 calls `page_header()` once; `inject_theme()` alone is idempotent and
safe to call from `demo/unified_app.py` on top of that.
"""

from __future__ import annotations

import streamlit as st

from common.constants import INSURER_NAME

_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Asap:wght@600;700&family=Source+Sans+3:wght@400;600;700&display=swap');

:root {
    --ams-ink: #363530;
    --ams-ink-soft: #6E6D66;
    --ams-accent: #A20A29;
    --ams-accent-hover: #850822;
    --ams-accent-ink: #7A0820;
    --ams-accent-soft: #F5E6E9;
    --ams-secondary: #005656;
    --ams-line: rgba(54,53,48,0.16);
    --ams-surface: #F7F7F6;
    --ams-shadow: 0 2px 10px rgba(147,148,142,0.3);
    /* Status colours are used as text, so they are held to WCAG AA 4.5:1
       against the lightest-on-darkest pairing they actually occur in. The
       previous #007F7F / #B08824 / #007CBF measured 4.27 / 2.90 / 4.00 on
       --ams-bg and failed. Keep these in step with the React console's
       theme.css, which was ported from this block. */
    --ams-success: #00706F;
    --ams-warning: #7D5F13;
    --ams-error: #D20D35;
    --ams-info: #00629A;
}

html, body, [class*="css"] {
    font-family: 'Source Sans 3', 'Source Sans Pro', system-ui, sans-serif;
}
h1, h2, h3 { font-family: 'Asap', system-ui, sans-serif; font-weight: 700 !important; }

.ams-header {
    padding: 0.25rem 0 1.1rem;
    margin-bottom: 0.75rem;
    border-bottom: 1px solid var(--ams-line);
}
.ams-header .ams-eyebrow {
    font-size: 0.72rem;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--ams-accent-ink);
    background: var(--ams-accent-soft);
    display: inline-block;
    padding: 0.2rem 0.55rem;
    border-radius: 2px;
    margin-bottom: 0.6rem;
}
.ams-header h1 {
    margin: 0 0 0.35rem !important;
    font-size: 2rem !important;
    color: var(--ams-ink);
}
.ams-header p {
    margin: 0;
    color: var(--ams-ink-soft);
    font-size: 0.98rem;
    max-width: 68ch;
}

[data-testid="stSidebar"] {
    background: var(--ams-surface);
}
[data-testid="stSidebar"] .ams-sidebar-title {
    font-family: 'Asap', system-ui, sans-serif;
    font-weight: 700;
    font-size: 1.05rem;
    color: var(--ams-ink);
    margin-bottom: 0.1rem;
}
[data-testid="stSidebar"] .ams-sidebar-caption {
    color: var(--ams-ink-soft);
    font-size: 0.82rem;
    margin-bottom: 1rem;
}

[data-testid="stMetricValue"] { color: var(--ams-accent-ink); }

[data-testid="stButton"] button {
    border-radius: 2px;
    box-shadow: none;
}
[data-testid="stButton"] button[kind="primary"] {
    background-color: var(--ams-accent);
    border-color: var(--ams-accent);
}
[data-testid="stButton"] button[kind="primary"]:hover {
    background-color: var(--ams-accent-hover);
    border-color: var(--ams-accent-hover);
}

a, a:visited { color: var(--ams-accent); }
a:hover { color: var(--ams-accent-hover); }

[data-testid="stVerticalBlockBorderWrapper"], div[data-baseweb="card"] {
    box-shadow: var(--ams-shadow);
    border-radius: 2px;
}
</style>
"""


def inject_theme() -> None:
    """Inject the shared CSS once per render. Safe to call multiple times —
    Streamlit dedupes identical markdown/CSS blocks in the DOM by re-render,
    and re-injecting the same `<style>` is harmless either way."""
    st.markdown(_CSS, unsafe_allow_html=True)


def page_header(scenario_code: str, title: str, subtitle: str) -> None:
    """Render the shared banner: eyebrow (insurer + scenario code), title,
    subtitle. Replaces a bare `st.title()` call so every scenario opens with
    the same visual identity, standalone or inside the unified nav."""
    inject_theme()
    st.markdown(
        f"""
        <div class="ams-header">
            <span class="ams-eyebrow">{INSURER_NAME} · AMS Console · {scenario_code}</span>
            <h1>{title}</h1>
            <p>{subtitle}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
