"""Login gate for the AMS console.

Replaces the old "Viewing as" free-choice picker in My Queue with an actual
credential check: pick your name, enter your passcode, and the session is
scoped to that identity for every scenario (S1 My Queue's ticket filter,
the Manager rollup) until "Log out" is clicked. Still a fictional roster on
a fictional passcode scheme, same footing as `ENGINEERS_BY_GROUP` itself —
not a real auth backend, no stored credentials file, nothing to rotate.

Passcode scheme (deliberately simple and presenter-memorable, not
security): each engineer's passcode is `1001 + their position in the
flattened ENGINEERS_BY_GROUP roster` (so Ravi Kumar/first entry -> 1001,
next -> 1002, and so on); the one "Manager" account is fixed at 9000.
"""

from __future__ import annotations

from dataclasses import dataclass

import streamlit as st

from common.constants import INSURER_NAME
from common.ui_theme import inject_theme
from s1_triage.engineer_assignment import ENGINEERS_BY_GROUP, group_for_engineer

MANAGER_NAME = "Manager"

ROSTER: list[str] = [name for names in ENGINEERS_BY_GROUP.values() for name in names]

PASSCODE_BY_NAME: dict[str, str] = {name: str(1001 + i) for i, name in enumerate(ROSTER)}
PASSCODE_BY_NAME[MANAGER_NAME] = "9000"

_SESSION_KEY = "ams_identity"


@dataclass(frozen=True)
class Identity:
    name: str
    role: str  # "engineer" | "manager"
    group: str | None


def authenticate(name: str, passcode: str) -> bool:
    return name in PASSCODE_BY_NAME and PASSCODE_BY_NAME[name] == passcode.strip()


def current_identity() -> Identity | None:
    return st.session_state.get(_SESSION_KEY)


def _login_form() -> None:
    inject_theme()
    st.markdown(
        '<div class="ams-header" style="border-bottom: none; padding-bottom: 0;">'
        f'<span class="ams-eyebrow">{INSURER_NAME} · AMS Console</span>'
        "</div>",
        unsafe_allow_html=True,
    )
    st.markdown("### Log in")
    st.caption("Pick your name and enter your passcode to see your queue.")
    with st.form("ams_login_form"):
        name = st.selectbox("Name", [*ROSTER, MANAGER_NAME])
        passcode = st.text_input("Passcode", type="password")
        submitted = st.form_submit_button("Log in", type="primary")
    if submitted:
        if authenticate(name, passcode):
            role = "manager" if name == MANAGER_NAME else "engineer"
            st.session_state[_SESSION_KEY] = Identity(
                name=name, role=role, group=group_for_engineer(name)
            )
            st.rerun()
        else:
            st.error("Name/passcode didn't match. Check the roster and try again.")


def render_login_gate() -> Identity:
    """Render the login form and halt the script here until authenticated.

    Call this once, first, from any standalone scenario entry point
    (`s1_triage/app.py::main()`) or the unified console
    (`demo/unified_app.py::main()`) — nothing else in that run renders until
    it returns, at which point the caller is guaranteed a logged-in
    `Identity`. Safe to call more than once per session (e.g. once from the
    unified console's gate and again implicitly via a scenario module) since
    it's a no-op once `ams_identity` is already set.
    """
    identity = current_identity()
    if identity is not None:
        return identity

    _login_form()
    st.stop()
    raise AssertionError("unreachable — st.stop() halts execution above")


def render_identity_chip() -> None:
    """Sidebar 'Logged in as X (role) · Log out' chip. Call after
    `render_login_gate()` from wherever the sidebar is being built."""
    identity = current_identity()
    if identity is None:
        return
    st.sidebar.markdown(f"**Logged in as {identity.name}** ({identity.role})")
    if st.sidebar.button("Log out"):
        del st.session_state[_SESSION_KEY]
        st.rerun()
