"""Streamlit view for the MapleSure policy/claims mock app.

Thin view only — no business logic, no direct sqlite3 calls. Everything
routes through mockapp/core/ (db.py, claims.py).
"""

from __future__ import annotations

import streamlit as st

from common.constants import INSURER_NAME
from common.ui_theme import inject_theme
from mockapp.core.claims import submit_claim
from mockapp.core.db import get_policy, init_db, list_claims, list_policies


def render() -> None:
    """Render the full MapleSure portal (everything except page config).

    Split out into a callable so a combined multi-scenario app (see
    demo/unified_app.py) can embed this scenario without a second
    st.set_page_config() call, which Streamlit forbids per session.
    Standalone launches (demo/run_s3.sh) still call st.set_page_config()
    once, below, before render().
    """
    init_db()

    # Deliberately a plain st.title(), not page_header(): this view represents
    # MapleSure's own policy/claims application, not one of our AMS scenario
    # tools — it should read as "the client's app", not "our AMS console".
    # inject_theme() still applies the shared fonts/spacing for visual
    # consistency without the AMS eyebrow banner.
    inject_theme()
    st.title(f"{INSURER_NAME} Policy Portal")

    policies = list_policies()

    st.header("Policies")
    st.dataframe(
        [
            {
                "Policy #": p.policy_number,
                "Holder": p.holder_name,
                "Product": p.product_type,
                "Premium": p.premium,
                "Start Date": p.start_date,
                "Status": p.status,
            }
            for p in policies
        ],
        use_container_width=True,
        hide_index=True,
    )

    st.header("Policy Detail")
    policy_numbers = [p.policy_number for p in policies]
    selected_number = st.selectbox("Select a policy", policy_numbers)

    if selected_number:
        policy = get_policy(selected_number)

        if policy is None:
            st.warning("Policy not found.")
        else:
            col1, col2, col3 = st.columns(3)
            col1.metric("Holder", policy.holder_name)
            col2.metric("Product", policy.product_type)
            col3.metric("Status", policy.status)
            st.write(f"Premium: ${policy.premium:,.2f}  |  Start date: {policy.start_date}")

            st.subheader("Claims on this policy")
            claims = list_claims(policy.policy_number)
            if claims:
                st.dataframe(
                    [
                        {
                            "Claim #": c.claim_number,
                            "Type": c.claim_type,
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
                st.write("No claims on file for this policy.")

            st.subheader("Submit a Claim")
            with st.form("submit_claim_form", clear_on_submit=True):
                claim_type = st.selectbox(
                    "Claim type",
                    ["Collision", "Theft", "Fire Damage", "Water Damage", "Windshield", "Other"],
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
                    )
                    st.success(f"Claim {new_claim.claim_number} submitted.")
                    st.rerun()


if __name__ == "__main__":
    st.set_page_config(page_title=f"{INSURER_NAME} — Policy Portal", layout="wide")
    render()
