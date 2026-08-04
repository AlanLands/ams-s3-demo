"""Shared constants used across scenario modules."""

AI_SUGGESTION_LABEL = "AI suggestion — verify with your specialist before applying."

# Deliberate, scoped exception to the human-in-the-loop rule above: a
# data-quality-gate "needs more info" mail is a low-risk request for details,
# not a resolution or a ticket action, so it is auto-sent without an engineer
# review step. Every other AI output in the app still uses AI_SUGGESTION_LABEL
# and waits for a human. Callers must label this clearly and distinctly so the
# one exception never reads as "AI output goes out unreviewed" in general.
AUTO_SENT_LABEL = "AI auto-sent — data-quality info request (no engineer review; demo exception)."

# Second deliberate, scoped exception to the human-in-the-loop rule above:
# self-service requests like a password reset or an ID card resend are the
# textbook "safe to fully automate" ITSM case — fully reversible, touch only
# the requestor's own account, no production or business-system change, and
# the response is a fixed template (no AI judgment call), unlike every other
# resolution this app drafts. Every other resolution still needs an
# engineer's approval before anything is sent. The confirmation text itself
# names which specific request type matched.
AUTO_RESOLVED_LABEL = (
    "AI auto-resolved — self-service request (no engineer review; demo exception)."
)

INSURER_NAME = "MapleSure Insurance"

# The application landscape the cross-team impact check is allowed to name.
# `analyze.draft_cross_team_impact` raises if the model returns anything
# outside this list, deliberately: a hallucinated application produces a Jira
# ticket for a team that does not exist, and the demo cannot show a repo for it.
#
# Not every name here has code in this repo. BillingGateway, NightlyBatch and
# IntegrationBridge are routing/impact destinations only — that is the point of
# them, and `applications.py` keeps "which team owns this" and "can we act on
# it" as two separate questions.
APPLICATIONS = [
    "PolicyCore",
    "BillingGateway",
    "DocumentHub",
    "NightlyBatch",
    "IntegrationBridge",
    "EnrolDirect",
]

ASSIGNMENT_GROUPS = [
    "App Support — PolicyCore",
    "App Support — BillingGateway",
    "App Support — DocumentHub",
    "Batch Ops",
    "Integration Support",
    "Service Desk L1",
]

PRIORITIES = ["P1", "P2", "P3", "P4"]
