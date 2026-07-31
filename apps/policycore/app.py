"""Streamlit view for the MapleSure group benefits mock app.

Thin view only — no business logic, no direct sqlite3 calls. Everything
routes through apps/policycore/core/ (db.py, claims.py).
"""

from __future__ import annotations

import streamlit as st

from common.constants import INSURER_NAME
from common.ui_theme import inject_theme
from apps.policycore.core.claims import submit_claim
from apps.policycore.core.db import (
    get_policy,
    init_db,
    list_claims,
    list_endorsements,
    list_plan_members,
    list_policies,
)
from apps.policycore.core.endorsements import submit_endorsement


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

    st.header("Group Contracts")
    st.dataframe(
        [
            {
                "Policy #": p.policy_number,
                "Plan Sponsor": p.holder_name,
                "Benefit": p.product_type,
                "Monthly Premium": p.premium,
                "Effective Date": p.start_date,
                "Status": p.status,
            }
            for p in policies
        ],
        use_container_width=True,
        hide_index=True,
    )

    st.header("Contract Detail")
    policy_numbers = [p.policy_number for p in policies]
    selected_number = st.selectbox("Select a group contract", policy_numbers)

    if selected_number:
        policy = get_policy(selected_number)

        if policy is None:
            st.warning("Group contract not found.")
        else:
            col1, col2, col3 = st.columns(3)
            col1.metric("Plan Sponsor", policy.holder_name)
            col2.metric("Benefit", policy.product_type)
            col3.metric("Status", policy.status)
            st.write(
                f"Monthly premium: ${policy.premium:,.2f}  |  "
                f"Effective date: {policy.start_date}"
            )

            st.subheader("Enrolled plan members")
            members = list_plan_members(policy.policy_number)
            if members:
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
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.write("No plan members enrolled under this contract.")

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
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.write("No claims on file for this contract.")

            st.subheader("Submit a Claim")
            with st.form("submit_claim_form", clear_on_submit=True):
                member_id = st.selectbox(
                    "Plan member",
                    [m.member_id for m in members] or [""],
                    format_func=lambda mid: next(
                        (f"{m.member_id} — {m.member_name}" for m in members if m.member_id == mid),
                        "No members enrolled",
                    ),
                )
                claim_type = st.selectbox(
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

            st.subheader("Endorsement Requests on this contract")
            endorsements = list_endorsements(policy.policy_number)
            if endorsements:
                st.dataframe(
                    [
                        {
                            "Endorsement #": e.endorsement_number,
                            "Type": e.endorsement_type,
                            "Requested Change": e.requested_change,
                            "Effective Date": e.effective_date,
                            "Contact Phone": e.contact_phone,
                            "Contact Email": e.contact_email,
                            "Filed At": e.filed_at,
                        }
                        for e in endorsements
                    ],
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.write("No endorsement requests on file for this contract.")

            st.subheader("Request a Contract Endorsement")
            with st.form("submit_endorsement_form", clear_on_submit=True):
                endorsement_type = st.selectbox(
                    "Endorsement type",
                    [
                        "Coverage Level Change",
                        "Dependent Add",
                        "Dependent Remove",
                        "Address Change",
                        "Name Correction",
                        "Other",
                    ],
                )
                requested_change = st.text_area("Describe the requested change")
                effective_date = st.date_input("Effective date")
                contact_phone = st.text_input("Contact phone")
                contact_email = st.text_input("Contact email")
                endorsement_submitted = st.form_submit_button("Submit Endorsement Request")

                if endorsement_submitted:
                    new_endorsement = submit_endorsement(
                        policy_number=policy.policy_number,
                        endorsement_type=endorsement_type,
                        requested_change=requested_change,
                        effective_date=str(effective_date),
                        contact_phone=contact_phone,
                        contact_email=contact_email,
                    )
                    st.success(
                        f"Endorsement request {new_endorsement.endorsement_number} submitted."
                    )
                    st.rerun()

if __name__ == "__main__":
    st.set_page_config(page_title=f"{INSURER_NAME} — Policy Portal", layout="wide")
    render()

