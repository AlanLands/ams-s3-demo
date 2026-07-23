"""FastAPI backend for the AMS console.

Thin routers over the exact same pure Python modules the Streamlit views
already called — see CLAUDE.md's Working style note on the React/FastAPI
migration. No pipeline/LLM/data logic lives here; it lives in common/,
s1_triage/, s2_problem/, etc. exactly as it did before this migration.
"""
