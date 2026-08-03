"""Streamlit view for the MapleSure group benefits mock app.

Thin view only — no business logic, no direct sqlite3 calls. Everything
routes through repos/policycore/core/ (db.py, claims.py).

Layout: a sidebar carries the contract picker and the section nav, and the
main pane shows the selected contract's header plus one section at a time,
rather than stacking every table and form into a single long scroll. Colours,
type and spacing come from .streamlit/config.toml — this file is inside the
codegen allowlist for both PolicyCore CRs and is replaced whole-file when a
proposal is applied, so styling written here would not survive an Apply.
"""

from __future__ import annotations

import streamlit as st

from common.constants import INSURER_NAME
from common.ui_theme import inject_theme
from repos.policycore.core.claims import submit_claim
from repos.policycore.core.db import (
    get_policy,
    init_db,
    list_claims,
    list_amendments,
    list_plan_members,
    list_policies,
)
from repos.policycore.core.amendments import submit_amendment

# Section is held in session_state under this key so a form submit's
# st.rerun() lands back on the section the administrator was already on
# instead of resetting them to the top of the portal.
_SECTION_KEY = "policycore_section"
_SECTIONS = ("Overview", "Plan members", "Claims", "Amendments")
_ALL_SPONSORS = "All plan sponsors"


def _money(amount: float) -> str:
    """Contributions and claim amounts read as money everywhere they appear."""
    return f"${amount:,.2f}"


def _sidebar_controls(policies: list) -> tuple[str | None, str, list]:
    """Render the contract picker and section nav.

    Returns the selected contract number, the chosen section, and the
    contracts surviving the sponsor filter — the Overview table renders that
    same filtered list, so the picker and the table can never disagree.
    """
    with st.sidebar:
        st.markdown(f"### {INSURER_NAME}")
        st.caption("Plan Administration Portal")
        st.divider()

        sponsors = sorted({p.sponsor_name for p in policies})
        sponsor = st.selectbox("Plan sponsor", [_ALL_SPONSORS, *sponsors])
        visible = [p for p in policies if sponsor == _ALL_SPONSORS or p.sponsor_name == sponsor]

        labels = {p.policy_number: f"{p.policy_number} — {p.product_type}" for p in visible}
        selected_number = None
        if visible:
            selected_number = st.selectbox(
                "Group contract",
                [p.policy_number for p in visible],
                format_func=lambda number: labels.get(number, number),
            )

        st.divider()
        section = st.radio("Go to", _SECTIONS, key=_SECTION_KEY)
        st.caption(f"Showing {len(visible)} of {len(policies)} group contracts")

    return selected_number, section, visible


def _contract_header(policy) -> None:
    """The selected contract, pinned above whichever section is open."""
    with st.container(border=True):
        st.markdown(f"**{policy.policy_number}** · {policy.sponsor_name}")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Benefit", policy.product_type)
        col2.metric("Plan tier", policy.plan_tier)
        col3.metric("Monthly contribution", _money(policy.contribution))
        col4.metric("Status", policy.status)
        st.caption(f"Effective date: {policy.start_date}")


def _overview_section(visible: list) -> None:
    """Book-of-business view: the totals, then the contracts behind them."""
    active = [p for p in visible if p.status == "Active"]
    col1, col2, col3 = st.columns(3)
    col1.metric("Group contracts", len(visible))
    col2.metric("Active", len(active))
    col3.metric("Monthly contributions", _money(sum(p.contribution for p in active)))

    st.subheader("Group Contracts")
    st.dataframe(
        [
            {
                "Policy #": p.policy_number,
                "Plan Sponsor": p.sponsor_name,
                "Benefit": p.product_type,
                "Plan Tier": p.plan_tier,
                "Monthly Contribution": p.contribution,
                "Effective Date": p.start_date,
                "Status": p.status,
            }
            for p in visible
        ],
        width="stretch",
        hide_index=True,
        column_config={
            "Monthly Contribution": st.column_config.NumberColumn(format="$%.2f"),
        },
    )


def _members_section(policy) -> None:
    st.subheader("Enrolled plan members")
    members = list_plan_members(policy.policy_number)
    if not members:
        st.info("No plan members enrolled under this contract.")
        return

    st.dataframe(
        [
            {
                "Member ID": m.member_id,
                "Member": m.member_name,
                "Dependents": m.dependents,
                "Enrolled On": m.enrolled_on,
                "Status": m.status,
            }
            for m in members
        ],
        width="stretch",
        hide_index=True,
    )


def _claims_section(policy) -> None:
    st.subheader("Claims on this contract")
    claims = list_claims(policy.policy_number)
    if claims:
        st.dataframe(
            [
                {
                    "Claim #": c.claim_number,
                    "Member": c.member_id,
                    "Service": c.claim_type,
                    "Amount": c.amount,
                    "Status": c.status,
                    "Filed At": c.filed_at,
                    "Notes": c.notes,
                }
                for c in claims
            ],
            width="stretch",
            hide_index=True,
            column_config={"Amount": st.column_config.NumberColumn(format="$%.2f")},
        )
    else:
        st.info("No claims on file for this contract.")

    members = list_plan_members(policy.policy_number)
    st.subheader("Submit a Claim")
    with st.container(border=True):
        with st.form("submit_claim_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            member_id = col1.selectbox(
                "Plan member",
                [m.member_id for m in members] or [""],
                format_func=lambda mid: next(
                    (f"{m.member_id} — {m.member_name}" for m in members if m.member_id == mid),
                    "No members enrolled",
                ),
            )
            claim_type = col2.selectbox(
                "Service type",
                [
                    "Paramedical",
                    "Prescription Drug",
                    "Dental Recall",
                    "Major Restorative",
                    "Vision",
                    "Short-Term Disability",
                    "Other",
                ],
            )
            amount = st.number_input("Claim amount ($)", min_value=0.0, step=50.0)
            notes = st.text_area("Notes")
            submitted = st.form_submit_button("Submit Claim")

            if submitted:
                new_claim = submit_claim(
                    policy_number=policy.policy_number,
                    claim_type=claim_type,
                    amount=amount,
                    notes=notes,
                    member_id=member_id,
                )
                st.success(f"Claim {new_claim.claim_number} submitted.")
                st.rerun()


def _amendments_section(policy) -> None:
    st.subheader("Amendment Requests on this contract")
    amendments = list_amendments(policy.policy_number)
    if amendments:
        st.dataframe(
            [
                {
                    "Amendment #": e.amendment_number,
                    "Type": e.amendment_type,
                    "Requested Change": e.requested_change,
                    "Effective Date": e.effective_date,
                    "Contact Phone": e.contact_phone,
                    "Contact Email": e.contact_email,
                    "Filed At": e.filed_at,
                }
                for e in amendments
            ],
            width="stretch",
            hide_index=True,
        )
    else:
        st.info("No amendment requests on file for this contract.")

    st.subheader("Request a Contract Amendment")
    with st.container(border=True):
        with st.form("submit_amendment_form", clear_on_submit=True):
            amendment_type = st.selectbox(
                "Amendment type",
                [
                    "Plan Tier Change",
                    "Dependent Add",
                    "Dependent Remove",
                    "Address Change",
                    "Name Correction",
                    "Other",
                ],
            )
            requested_change = st.text_area("Describe the requested change")
            effective_date = st.date_input("Effective date")
            col1, col2 = st.columns(2)
            contact_phone = col1.text_input("Contact phone")
            contact_email = col2.text_input("Contact email")
            amendment_submitted = st.form_submit_button("Submit Amendment Request")

            if amendment_submitted:
                new_amendment = submit_amendment(
                    policy_number=policy.policy_number,
                    amendment_type=amendment_type,
                    requested_change=requested_change,
                    effective_date=str(effective_date),
                    contact_phone=contact_phone,
                    contact_email=contact_email,
                )
                st.success(f"Amendment request {new_amendment.amendment_number} submitted.")
                st.rerun()


def render() -> None:
    """Render the full MapleSure plan administration portal (except page config).

    Split out into a callable so a combined multi-scenario app (see
    demo/unified_app.py) can embed this scenario without a second
    st.set_page_config() call, which Streamlit forbids per session.
    Standalone launches (demo/run_s3.sh) still call st.set_page_config()
    once, below, before render().
    """
    init_db()

    # Deliberately a plain st.title(), not page_header(): this view represents
    # MapleSure's own group benefits application, not one of our AMS scenario
    # tools — it should read as "the client's app", not "our AMS console".
    # inject_theme() still applies the shared fonts/spacing for visual
    # consistency without the AMS eyebrow banner.
    inject_theme()
    st.title(f"{INSURER_NAME} Plan Administration Portal")

    policies = list_policies()
    if not policies:
        st.warning("No group contracts on file.")
        return

    selected_number, section, visible = _sidebar_controls(policies)
    if not selected_number:
        st.warning("No group contract matches the current filter.")
        return

    policy = get_policy(selected_number)

    if policy is None:
        st.warning("Group contract not found.")
    else:
        _contract_header(policy)

        if section == "Overview":
            _overview_section(visible)
        elif section == "Plan members":
            _members_section(policy)
        elif section == "Claims":
            _claims_section(policy)
        else:
            _amendments_section(policy)


if __name__ == "__main__":
    st.set_page_config(page_title=f"{INSURER_NAME} — Policy Portal", layout="wide")
    render()
