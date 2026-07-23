"""Thin Streamlit view for S1 incident triage and resolution."""

from __future__ import annotations

import os
from collections import Counter

import altair as alt
import pandas as pd
import streamlit as st

from common.constants import (
    AI_SUGGESTION_LABEL,
    APPLICATIONS,
    AUTO_RESOLVED_LABEL,
    AUTO_SENT_LABEL,
)
from common.llm import LLMError
from common.schema import Incident
from common.ticket_events import Actor, events_for, record_event
from common.ui_pipeline import render_pipeline_stepper, render_stage_detail
from common.ui_theme import page_header
from common.ui_timeline import render_timeline
from s1_triage.batch import run_batch
from s1_triage.chatbot import answer_question
from s1_triage.data_access import KbArticle, load_incidents, load_kb_articles
from s1_triage.engineer_assignment import (
    ENGINEERS_BY_GROUP,
    assign_engineer,
    assigned_engineer_for,
    current_bandwidth,
    open_incidents_for,
    team_bandwidth,
)
from s1_triage.funnel import FunnelClassification, classify, classify_all
from s1_triage.funnel_metrics import STAGE_ORDER, funnel_counts
from s1_triage.quality_gate import assess
from s1_triage.queue_status import QUEUE_STATUS_LABELS, QUEUE_STATUS_ORDER, queue_statuses
from s1_triage.resolution import draft_resolution
from s1_triage.roster_auth import current_identity, render_login_gate
from s1_triage.routing import route
from s1_triage.similar_incidents import find_similar
from s1_triage.triage import TriageResult, apply_arbitration, triage

_STAGE_LABELS = {
    "auto_triaged": "Auto-triaged",
    "needs_engineer_review": "Needs engineer review",
    "needs_more_info": "Needs more info from requestor",
}

# Categorical slots 1 (green), 3 (amber), 5 (red) from the project's validated
# palette (see tools/cost_dashboard.py for the same light/dark-aware pattern).
_STAGE_PALETTE = {
    "light": {
        "auto_triaged": "#008300",
        "needs_engineer_review": "#c27600",
        "needs_more_info": "#c22e00",
    },
    "dark": {
        "auto_triaged": "#3ba33b",
        "needs_engineer_review": "#d9a441",
        "needs_more_info": "#e0654a",
    },
}

# Same red/amber/green as _STAGE_PALETTE (this is a different axis — live queue
# status, not triage forecast — but green/amber/red carry the same "done /
# needs a touch / needs the most work" meaning in both, so reusing the exact
# hues keeps that reading consistent). Blue for "info requested" reuses
# tools/cost_dashboard.py's slot-1 blue — a neutral, "blocked on the
# requestor, not on us" signal distinct from the other three.
_QUEUE_STATUS_PALETTE = {
    "light": {
        "needs_human_review": "#c22e00",
        "awaiting_engineer_approval": "#c27600",
        "info_requested": "#2a78d6",
        "ai_resolved": "#008300",
    },
    "dark": {
        "needs_human_review": "#e0654a",
        "awaiting_engineer_approval": "#d9a441",
        "info_requested": "#3987e5",
        "ai_resolved": "#3ba33b",
    },
}


@st.cache_data(show_spinner=False)
def _load_incidents_cached() -> list[Incident]:
    return load_incidents()


@st.cache_data(show_spinner=False)
def _classify_all_cached() -> list[FunnelClassification]:
    # No LLM calls here — funnel.classify_all() is deterministic (rules + TF-IDF
    # similarity only), so this is fast and unaffected by demo/reset_s1.sh clearing
    # .cache/llm. Takes its own incidents copy rather than accepting the cached list
    # as an argument, matching _load_kb_articles_cached()'s no-arg pattern below.
    return classify_all(_load_incidents_cached())


@st.cache_data(show_spinner=False)
def _load_kb_articles_cached() -> list[KbArticle]:
    return load_kb_articles()


def _selected_row_index(selection) -> int | None:
    # selection_mode=["single-row", "single-cell"] below is deliberate: Streamlit
    # only toggles `.rows` when the tiny leftmost checkbox itself is clicked —
    # clicking anywhere else in the row just highlights that one cell without
    # selecting it. Adding "single-cell" makes a click on ANY cell report
    # `.cells` as [(row_index, column_name)], so a click anywhere in the row
    # resolves to that row — the UX a presenter actually expects.
    if selection.rows:
        return selection.rows[0]
    if selection.cells:
        return selection.cells[0][0]
    return None


def _render_quality_verdict(verdict) -> None:
    st.markdown(f"**{AI_SUGGESTION_LABEL}**")
    cols = st.columns([1, 1, 3])
    cols[0].metric("Investigable", "Yes" if verdict.investigable else "No")
    cols[1].metric("Score", f"{verdict.score:.2f}")
    with cols[2]:
        st.write(verdict.reasoning)
        if verdict.missing_info:
            st.caption("Missing: " + ", ".join(verdict.missing_info))


def _render_rule_match(rule_match) -> None:
    st.markdown("**Rule match**")
    if rule_match is None:
        st.info("No editable application rule fired.")
        return
    st.info(
        f"**{rule_match.rule_name}** — category: {rule_match.suggested_category}, "
        f"priority: {rule_match.suggested_priority}\n\n{rule_match.why}"
    )


def _render_triage_result(triage_result) -> None:
    st.markdown(f"**{AI_SUGGESTION_LABEL}**")
    cols = st.columns([1, 1, 3])
    cols[0].metric("AI category", triage_result.ai_category)
    cols[1].metric("AI priority", triage_result.ai_priority)
    cols[2].write(triage_result.ai_reasoning)


def _triage_review_gate(incident: Incident, triage_result: TriageResult) -> TriageResult | None:
    """Agreement-gated review: agree auto-proceeds; deviation and AI-only pause
    the pipeline until the engineer arbitrates/confirms. Returns the verdict to
    continue with, or None while paused (caller stops before routing)."""
    if triage_result.agreement == "agree":
        st.success(
            f"✅ Rule & AI agree ({triage_result.final_priority} / "
            f"{triage_result.final_category}) — auto-triaged, no engineer review needed."
        )
        _record_timeline_once(
            incident.number,
            "ai",
            "triage_agreement",
            "Rule and AI verdicts agree — auto-proceeded without engineer review.",
        )
        return triage_result

    state_key = f"arbitration_{incident.number}"
    choice = st.session_state.get(state_key)

    if triage_result.agreement == "ai_only":
        st.warning(
            "⚠️ AI-only verdict — no application rule fired, so there is no rule "
            "guardrail. Engineer must confirm before routing continues."
        )
        if choice is None and st.button(
            f"Confirm AI verdict ({triage_result.ai_priority} / {triage_result.ai_category})"
        ):
            st.session_state[state_key] = choice = "accept_ai"
        if choice is None:
            st.info("Pipeline paused — routing and resolution draft run after confirmation.")
            return None
        confirmed = apply_arbitration(triage_result, choice)
        _record_timeline_once(
            incident.number,
            "human",
            "triage_confirmed",
            f"Engineer confirmed AI-only verdict "
            f"{confirmed.final_priority} / {confirmed.final_category}.",
        )
        return confirmed

    rule = triage_result.rule_match
    assert rule is not None  # agreement == "deviation" implies a fired rule
    st.warning(
        f"⚠️ AI deviates from rule '{rule.rule_name}' on "
        f"{' and '.join(triage_result.deviating_fields)}: rule says "
        f"{rule.suggested_priority} / {rule.suggested_category}, AI says "
        f"{triage_result.ai_priority} / {triage_result.ai_category}. "
        "Engineer arbitration required."
    )
    if choice is None:
        col_rule, col_ai = st.columns(2)
        if col_rule.button(
            f"Keep rule verdict ({rule.suggested_priority} / {rule.suggested_category})"
        ):
            st.session_state[state_key] = choice = "keep_rule"
        if col_ai.button(
            f"Accept AI verdict ({triage_result.ai_priority} / {triage_result.ai_category})"
        ):
            st.session_state[state_key] = choice = "accept_ai"
    if choice is None:
        st.info("Pipeline paused — routing and resolution draft run after arbitration.")
        return None
    arbitrated = apply_arbitration(triage_result, choice)
    chose = "kept the rule verdict" if choice == "keep_rule" else "accepted the AI verdict"
    _record_timeline_once(
        incident.number,
        "human",
        "triage_arbitration",
        f"Engineer {chose}: {arbitrated.final_priority} / {arbitrated.final_category}.",
    )
    return arbitrated


def _render_routing_result(routing_result, incidents: list[Incident]) -> None:
    st.markdown("**Suggested assignment**")
    st.write(f"**Assignment group:** {routing_result.assignment_group}")
    st.caption(routing_result.citation)
    # Informational only — workload is not a routing input, just context an
    # engineer would want alongside the group name (the target group doesn't
    # change based on this count).
    open_count = sum(
        1
        for row in incidents
        if row.assignment_group == routing_result.assignment_group and not row.resolved_at
    )
    st.caption(f"Current open workload in this group: {open_count} ticket(s).")


def _render_similar_incidents(similar) -> None:
    st.markdown("**Similar incidents**")
    if not similar:
        st.caption("No prior incidents scored above the similarity threshold.")
        return
    st.dataframe(
        [
            {
                "incident_number": item.incident_number,
                "similarity_score": item.similarity_score,
                "resolution_notes": item.resolution_notes,
            }
            for item in similar
        ],
        use_container_width=True,
    )


def _render_resolution_draft(draft) -> None:
    st.markdown(f"**{AI_SUGGESTION_LABEL}**")
    st.text_area("Resolution steps", draft.resolution_steps, height=160)
    st.text_area("Work note", draft.work_note, height=120)
    st.text_area("Requestor email", draft.requestor_email, height=140)


def _record_timeline_once(
    ticket_number: str,
    actor: Actor,
    action: str,
    detail: str = "",
) -> None:
    key = f"timeline_{ticket_number}_{actor}_{action}_{detail}"
    if st.session_state.get(key):
        return
    try:
        record_event(ticket_number, actor, action, detail)
        st.session_state[key] = True
    except OSError as exc:
        st.caption(f"Timeline event could not be saved ({exc}).")


def _render_ticket_timeline(ticket_number: str) -> None:
    try:
        events = events_for(ticket_number)
    except OSError as exc:
        st.caption(f"Timeline unavailable ({exc}).")
        return
    with st.expander("Ticket timeline", expanded=True):
        render_timeline(events)


def _render_funnel_badge(incident: Incident, incidents: list[Incident]) -> None:
    # Reuses the same funnel.classify() the Triage Funnel view uses — one code path,
    # not a second opinion. Label-only: the pipeline below already runs every stage
    # automatically regardless of this verdict, so there's no new gating behavior
    # here, just naming what's already true.
    result = classify(incident, incidents)
    if result.stage == "auto_triaged":
        st.success(f"✅ {_STAGE_LABELS[result.stage]} — {result.reasoning}")
    elif result.stage == "needs_engineer_review":
        st.warning(f"⚠️ {_STAGE_LABELS[result.stage]} — {result.reasoning}")
    else:
        st.error(f"⚠️ {_STAGE_LABELS[result.stage]} — {result.reasoning}")


def _render_incident_pipeline(incident: Incident, incidents: list[Incident]) -> None:
    """Full per-incident pipeline detail — quality gate through resolution draft.

    Reachable only from My Queue, scoped to a ticket already assigned to the
    viewing engineer by the background pass (`s1_triage.batch.run_batch`).
    Self-service tickets never appear here: they auto-resolve in the
    background without ever getting an `engineer_assigned` event, so they're
    never in anyone's queue. Engineer identity itself is never re-decided
    here — see `assigned_engineer_for`'s docstring.
    """
    st.subheader(f"{incident.number}: {incident.short_description}")
    sla_flag = " | SLA BREACHED" if incident.sla_breached else ""
    st.caption(
        f"{incident.application} | {incident.category}/{incident.subcategory} | "
        f"Priority {incident.priority}{sla_flag}"
    )
    _render_funnel_badge(incident, incidents)

    # The AI-dependent pipeline runs as one block: a live-call failure must not
    # crash the page (Streamlit reruns the whole script), it should just stop the
    # AI steps gracefully and leave the incident header above visible. Several
    # sequential live LLM calls can take 20-30+ seconds uncached — the spinner is
    # the only thing telling the engineer the page is working, not stuck.
    stepper_slot = st.empty()
    stage_names = [
        "Quality Gate",
        "Triage",
        "Routing",
        "Engineer Assignment",
        "Similar Incidents",
        "Resolution Draft",
    ]
    stage_status: dict[str, str] = {name: "pending" for name in stage_names}

    def _render_stepper(active: str | None) -> None:
        if active is not None:
            stage_status[active] = "active"
        render_pipeline_stepper(
            [(name, stage_status[name]) for name in stage_names],
            container=stepper_slot,
        )

    _render_stepper("Quality Gate")
    try:
        with st.spinner("Running AI pipeline (quality gate, triage, routing, similar-incident "
                         "lookup, resolution draft)..."):
            verdict = assess(incident)
            verdict_detail = (
                f"{'investigable' if verdict.investigable else 'needs more info'} — "
                f"{verdict.reasoning}"
            )
            _record_timeline_once(incident.number, "ai", "quality_gate", verdict_detail)
            _render_quality_verdict(verdict)
            render_stage_detail(
                "Quality gate reasoning", reasoning=verdict.reasoning, confidence=verdict.score
            )
            stage_status["Quality Gate"] = "done"

            if not verdict.investigable:
                _render_stepper(None)
                st.error(
                    "Quality gate: not investigable as-is. Pipeline stops here — triage, "
                    "routing, similar-incident lookup, and resolution drafting do not run "
                    "against an incident that failed this gate."
                )
                if verdict.drafted_requestor_mail:
                    # Scoped exception to human-in-the-loop: see AUTO_SENT_LABEL's
                    # definition in common/constants.py for why this one flow skips
                    # engineer review while every other AI output in the app doesn't.
                    _record_timeline_once(
                        incident.number,
                        "system",
                        "requestor_mail_auto_sent",
                        "Auto-sent info-request email to requestor (no engineer review).",
                    )
                    st.markdown(f"**{AUTO_SENT_LABEL}**")
                    st.text_area(
                        "Requestor mail (auto-sent)",
                        verdict.drafted_requestor_mail,
                        height=140,
                        disabled=True,
                    )
                return

            _render_stepper("Triage")
            triage_result = triage(incident)
            _record_timeline_once(
                incident.number,
                "ai",
                "triage",
                f"{triage_result.ai_priority} / {triage_result.ai_category}",
            )
            _render_rule_match(triage_result.rule_match)
            _render_triage_result(triage_result)
            rule_match = triage_result.rule_match
            render_stage_detail(
                "Triage reasoning",
                reasoning=triage_result.ai_reasoning,
                signals=(
                    [f"Rule: {rule_match.rule_name} — {rule_match.why}"] if rule_match else []
                ),
            )

            gated_result = _triage_review_gate(incident, triage_result)
            if gated_result is None:
                # Still "active", not "done" — the stepper honestly shows the
                # pipeline paused mid-triage until the engineer arbitrates.
                _render_stepper(None)
                _render_ticket_timeline(incident.number)
                return
            triage_result = gated_result
            stage_status["Triage"] = "done"

            _render_stepper("Routing")
            routing_result = route(incident, triage_result)
            _record_timeline_once(
                incident.number,
                "ai",
                "routing",
                routing_result.assignment_group,
            )
            _render_routing_result(routing_result, incidents)
            stage_status["Routing"] = "done"

            _render_stepper("Engineer Assignment")
            # Read-only: assignment already happened once, in the background
            # pass — re-deciding here could pick someone else as bandwidth
            # shifts and double-book the ticket across two queues.
            engineer = assigned_engineer_for(incident.number)
            if engineer is None:
                # Safety net only — shouldn't happen since My Queue only lists
                # already-assigned tickets, but self-heal rather than crash.
                assignment = assign_engineer(incident, routing_result, incidents)
                _record_timeline_once(
                    incident.number, "ai", "engineer_assigned", assignment.engineer
                )
                engineer = assignment.engineer
            st.markdown("**Engineer assignment**")
            st.write(f"**Assigned to:** {engineer}")
            st.caption(
                f"Current weighted bandwidth: {current_bandwidth(engineer, incidents)}."
            )
            stage_status["Engineer Assignment"] = "done"

            _render_stepper("Similar Incidents")
            similar = find_similar(incident, incidents)
            _record_timeline_once(
                incident.number,
                "ai",
                "similar_incidents",
                f"{len(similar)} matching historical incident(s) surfaced.",
            )
            _render_similar_incidents(similar)
            render_stage_detail(
                "Similar-incident signals",
                signals=[
                    f"{match.incident_number} (similarity {match.similarity_score:.2f}): "
                    f"{match.resolution_notes}"
                    for match in similar
                ],
            )
            stage_status["Similar Incidents"] = "done"

            _render_stepper("Resolution Draft")
            draft = draft_resolution(incident, similar, _load_kb_articles_cached())
            _record_timeline_once(
                incident.number,
                "ai",
                "resolution_draft",
                "Drafted work note, resolution steps, and requestor email.",
            )
            _render_resolution_draft(draft)
            stage_status["Resolution Draft"] = "done"
            _render_stepper(None)
    except LLMError as exc:
        _render_stepper(None)
        st.warning(f"AI pipeline unavailable ({exc}). Incident details above are unaffected.")
        return

    if st.button("Mark as reviewed & approved"):
        st.session_state[f"approved_{incident.number}"] = True
        _record_timeline_once(
            incident.number,
            "human",
            "approved_resolution",
            "Support engineer approved the drafted ticket update.",
        )
    if st.session_state.get(f"approved_{incident.number}"):
        st.success(
            "Reviewed by support engineer. Ticket update is ready; nothing was sent or closed."
        )
        _record_timeline_once(
            incident.number,
            "system",
            "resolved",
            "Ticket update prepared after human approval; closure stays with the client.",
        )

    _render_ticket_timeline(incident.number)


def _mode() -> str:
    return "dark" if st.get_option("theme.base") == "dark" else "light"


def _metric_tile_css(keys_and_colors: dict[str, str]) -> None:
    # st.container(key=...) exposes a `.st-key-<key>` class on its wrapper div —
    # this is how a single st.metric among several gets its own accent color,
    # since [data-testid="stMetric"] alone is shared by every metric on the page.
    rules = "".join(
        f'.st-key-{key} [data-testid="stMetric"] {{ border-left: 4px solid {color}; '
        "padding-left: 0.6rem; }"
        for key, color in keys_and_colors.items()
    )
    st.markdown(f"<style>{rules}</style>", unsafe_allow_html=True)


def _funnel_kpi_row(classifications: list[FunnelClassification]) -> None:
    total = len(classifications)
    counts = funnel_counts(classifications)
    palette = _STAGE_PALETTE[_mode()]

    _metric_tile_css({f"stage-{stage}": palette[stage] for stage in STAGE_ORDER})
    cols = st.columns(4)
    with cols[0].container(border=True):
        st.metric("Incidents reported", total)
    for col, stage in zip(cols[1:4], STAGE_ORDER, strict=True):
        count = counts[stage]
        pct = f"{count / total:.0%}" if total else "—"
        with col.container(key=f"stage-{stage}", border=True):
            st.metric(_STAGE_LABELS[stage], count, help=f"{pct} of reported incidents")


def _queue_status_kpi_row(classifications: list[FunnelClassification]) -> None:
    stage_by_number = {item.incident_number: item.stage for item in classifications}
    counts = Counter(queue_statuses(stage_by_number).values())
    palette = _QUEUE_STATUS_PALETTE[_mode()]

    _metric_tile_css({f"qs-{status}": palette[status] for status in QUEUE_STATUS_ORDER})
    cols = st.columns(len(QUEUE_STATUS_ORDER))
    for col, status in zip(cols, QUEUE_STATUS_ORDER, strict=True):
        with col.container(key=f"qs-{status}", border=True):
            st.metric(QUEUE_STATUS_LABELS[status], counts.get(status, 0))


def _funnel_chart(classifications: list[FunnelClassification]) -> alt.Chart:
    counts = funnel_counts(classifications)
    df = pd.DataFrame(
        {
            "stage": [_STAGE_LABELS[stage] for stage in STAGE_ORDER],
            "stage_key": STAGE_ORDER,
            "count": [counts[stage] for stage in STAGE_ORDER],
        }
    )
    palette = _STAGE_PALETTE[_mode()]
    color_range = [palette[stage] for stage in STAGE_ORDER]
    return (
        alt.Chart(df)
        .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
        .encode(
            x=alt.X("stage:N", title="Triage outcome", sort=list(df["stage"])),
            y=alt.Y("count:Q", title="Incidents"),
            color=alt.Color(
                "stage_key:N",
                title="Outcome",
                scale=alt.Scale(domain=STAGE_ORDER, range=color_range),
                legend=None,
            ),
            tooltip=["stage", "count"],
        )
        .properties(height=280)
    )


def _funnel_table(
    classifications: list[FunnelClassification],
    incidents: list[Incident],
    applications: list[str],
    stages: list[str],
    queue_status_filter: list[str],
) -> str | None:
    incident_by_number = {incident.number: incident for incident in incidents}
    stage_by_number = {item.incident_number: item.stage for item in classifications}
    statuses = queue_statuses(stage_by_number)

    rows = []
    row_incident_numbers = []
    for item in classifications:
        if stages and item.stage not in stages:
            continue
        status = statuses[item.incident_number]
        if queue_status_filter and status not in queue_status_filter:
            continue
        incident = incident_by_number[item.incident_number]
        if applications and incident.application not in applications:
            continue
        rows.append(
            {
                "incident_number": item.incident_number,
                "application": incident.application,
                "category": incident.category,
                "outcome": _STAGE_LABELS[item.stage],
                "queue_status": QUEUE_STATUS_LABELS[status],
                "reasoning": item.reasoning,
            }
        )
        row_incident_numbers.append(item.incident_number)

    # Same row-selection pattern as My Queue's ticket picker — see
    # _selected_row_index() for why "single-cell" is included. Selection
    # indices are positions in `rows`/`row_incident_numbers`, stable across
    # client-side sort.
    event = st.dataframe(
        rows,
        use_container_width=True,
        height=320,
        hide_index=True,
        on_select="rerun",
        selection_mode=["single-row", "single-cell"],
    )
    st.caption(
        "Tip: click a row to see full incident details below. Sorting a column clears your "
        "selection."
    )

    selected_index = _selected_row_index(event.selection)
    if selected_index is None:
        return None
    return row_incident_numbers[selected_index]


def _render_incident_detail(
    incident_number: str,
    classifications: list[FunnelClassification],
    incidents: list[Incident],
) -> None:
    incident = next(i for i in incidents if i.number == incident_number)
    classification = next(c for c in classifications if c.incident_number == incident_number)
    stage_by_number = {c.incident_number: c.stage for c in classifications}
    status = queue_statuses(stage_by_number)[incident_number]

    st.subheader(f"{incident.number}: {incident.short_description}")
    sla_flag = " | SLA BREACHED" if incident.sla_breached else ""
    st.caption(
        f"{incident.application} | {incident.category}/{incident.subcategory} | "
        f"Priority {incident.priority}{sla_flag}"
    )
    cols = st.columns([1, 1.6, 1])
    cols[0].metric("Triage outcome", _STAGE_LABELS[classification.stage])
    cols[1].metric("Queue status", QUEUE_STATUS_LABELS[status])
    cols[2].metric("Assignment group", incident.assignment_group)
    st.write(incident.description)
    st.caption(classification.reasoning)
    if incident.resolution_notes:
        st.markdown("**Resolution notes on file**")
        st.write(incident.resolution_notes)


def _triage_funnel_mode() -> None:
    incidents = _load_incidents_cached()
    with st.spinner("Classifying incidents (rules + Knowledge Repository match, no LLM call)..."):
        classifications = _classify_all_cached()

    st.caption(
        "Deterministic — based on the editable rule engine and Knowledge Repository "
        "(past-incident) match confidence, not an LLM call. The AI-drafted "
        f'resolution for an "{_STAGE_LABELS["auto_triaged"]}" ticket still needs '
        "an engineer's sign-off before anything is sent — this only shows how many "
        "tickets don't need a human to figure out *what* they are."
    )
    _funnel_kpi_row(classifications)
    st.altair_chart(_funnel_chart(classifications), use_container_width=True)

    st.subheader("Ticket queue status")
    st.caption(
        "Live per-ticket progress — updates as the background pipeline processes "
        "incidents and engineers review them in My Queue this session. A ticket with "
        "no activity yet falls back "
        f'to the forecast above: "{_STAGE_LABELS["auto_triaged"]}" reads as '
        f'"{QUEUE_STATUS_LABELS["awaiting_engineer_approval"]}", everything else '
        f'reads as "{QUEUE_STATUS_LABELS["needs_human_review"]}".'
    )
    _queue_status_kpi_row(classifications)

    st.subheader("Incidents")
    cols = st.columns(3)
    applications = cols[0].multiselect("Application", APPLICATIONS)
    stages = cols[1].multiselect(
        "Outcome", options=STAGE_ORDER, format_func=lambda stage: _STAGE_LABELS[stage]
    )
    queue_status_filter = cols[2].multiselect(
        "Queue status", options=QUEUE_STATUS_ORDER, format_func=lambda s: QUEUE_STATUS_LABELS[s]
    )
    selected_number = _funnel_table(
        classifications, incidents, applications, stages, queue_status_filter
    )
    if selected_number:
        _render_incident_detail(selected_number, classifications, incidents)


def _chatbot_mode() -> None:
    question = st.text_input("Ask about incident history or KB articles")
    if question:
        try:
            with st.spinner("Asking..."):
                answer = answer_question(question)
            st.write(answer)
        except LLMError as exc:
            st.warning(f"AI pipeline unavailable ({exc}). Try again once the issue clears.")


def _batch_table(incidents: list[Incident], notes: dict[str, str]) -> None:
    classifications = _classify_all_cached()
    stage_by_number = {item.incident_number: item.stage for item in classifications}
    statuses = queue_statuses(stage_by_number)

    rows = [
        {
            "incident_number": incident.number,
            "application": incident.application,
            "queue_status": QUEUE_STATUS_LABELS[statuses[incident.number]],
            "pipeline_result": notes.get(incident.number, ""),
        }
        for incident in incidents
    ]
    st.dataframe(rows, use_container_width=True, height=400)


def _batch_mode() -> None:
    incidents = _load_incidents_cached()
    st.caption(
        "Processes every incident in one click — this is the same background pass "
        "My Queue triggers automatically the first time it's opened this session. "
        "Self-service requests "
        f'(**{AUTO_RESOLVED_LABEL}**) auto-resolve instantly with no engineer '
        "review; everything else runs the full quality-gate → triage → routing → "
        "engineer-assignment → similar-incident → resolution-draft pipeline and lands "
        'in a specific engineer\'s My Queue as "Awaiting engineer approval" or "Needs '
        'human review." Nothing is sent to a requestor without review except the two '
        "scoped exceptions labeled throughout this app."
    )
    if st.button("Run batch", type="primary"):
        kb_articles = _load_kb_articles_cached()
        with st.spinner(f"Processing {len(incidents)} incidents..."):
            results = run_batch(incidents, incidents, kb_articles)
        st.session_state["batch_results"] = {r.incident_number: r.note for r in results}

    notes = st.session_state.get("batch_results")
    if notes is None:
        st.info('Click "Run batch" to process every incident.')
        return

    _queue_status_kpi_row(_classify_all_cached())
    st.subheader("Batch results")
    _batch_table(incidents, notes)


def _ensure_background_processing_ran() -> None:
    """Run the same headless pipeline Batch mode uses, once per session, so
    tickets are already quality-gated / triaged / routed / assigned before
    anyone opens My Queue — "AI processing" is something that already
    happened, not a button an engineer has to click. Shares the
    `batch_results` session key with Batch mode: whichever runs first primes
    it for the other, so re-running is never duplicated work."""
    if st.session_state.get("batch_results") is not None:
        return
    incidents = _load_incidents_cached()
    kb_articles = _load_kb_articles_cached()
    with st.spinner("AI processing tickets in the background (quality gate → triage → "
                     "routing → engineer assignment → similar-incident lookup → "
                     "resolution draft)..."):
        results = run_batch(incidents, incidents, kb_articles)
    st.session_state["batch_results"] = {r.incident_number: r.note for r in results}


def _manager_view(incidents: list) -> None:
    st.caption(
        "Manager rollup — every assignment group's queue and bandwidth at once, "
        "the portfolio-level view a single engineer's login can't reach."
    )
    all_open = 0
    all_sla_at_risk = 0
    for group in ENGINEERS_BY_GROUP:
        group_incidents = [
            incident
            for name in ENGINEERS_BY_GROUP[group]
            for incident in open_incidents_for(name, incidents)
        ]
        all_open += len(group_incidents)
        all_sla_at_risk += sum(1 for incident in group_incidents if incident.sla_breached)

    cols = st.columns(2)
    cols[0].metric("Open tickets — all groups", all_open)
    cols[1].metric("SLA at risk — all groups", all_sla_at_risk)

    for group in ENGINEERS_BY_GROUP:
        with st.expander(group, expanded=False):
            st.dataframe(
                [
                    {"engineer": name, "open_tickets": count, "weighted_bandwidth": load}
                    for name, count, load in team_bandwidth(group, incidents)
                ],
                use_container_width=True,
                hide_index=True,
            )


def _my_queue_mode() -> None:
    _ensure_background_processing_ran()
    incidents = _load_incidents_cached()
    identity = current_identity()

    if identity.role == "manager":
        _manager_view(incidents)
        return

    engineer = identity.name
    group = identity.group
    st.caption("Queue scoped to your login — you only ever see your own tickets.")

    my_incidents = open_incidents_for(engineer, incidents)
    bandwidth = current_bandwidth(engineer, incidents)
    sla_at_risk = sum(1 for incident in my_incidents if incident.sla_breached)

    cols = st.columns(3)
    cols[0].metric("Assigned to me", len(my_incidents))
    cols[1].metric("Weighted bandwidth", bandwidth)
    cols[2].metric("SLA at risk", sla_at_risk)

    if group:
        st.subheader(f"Team bandwidth — {group}")
        st.caption(
            "How the AI is balancing load across this group's engineers right now — "
            "weighted by ticket complexity (priority + prior reassignments), not just count."
        )
        st.dataframe(
            [
                {"engineer": name, "open_tickets": count, "weighted_bandwidth": load}
                for name, count, load in team_bandwidth(group, incidents)
            ],
            use_container_width=True,
            hide_index=True,
        )

    st.subheader("My tickets")
    if not my_incidents:
        st.info(f"No tickets currently assigned to {engineer} this session.")
        return

    ticket_labels = [
        f"{incident.number} | {incident.priority} | {incident.application} | "
        f"{incident.short_description}"
        for incident in my_incidents
    ]
    selected_ticket_label = st.radio("Select a ticket to open", ticket_labels)
    selected_incident = my_incidents[ticket_labels.index(selected_ticket_label)]

    with st.container(border=True):
        _render_incident_pipeline(selected_incident, incidents)


def _render_dev_tools_link() -> None:
    # Off by default so this never shows during the actual client demo — the cost
    # dashboard (tools/cost_dashboard.py) is an internal tool, not a demo beat.
    # Set SHOW_DEV_TOOLS=1 for internal/team use.
    if os.environ.get("SHOW_DEV_TOOLS") != "1":
        return
    dashboard_url = os.environ.get("COST_DASHBOARD_URL", "http://localhost:8510")
    st.sidebar.markdown("**Internal tools**")
    st.sidebar.link_button("LLM cost & usage telemetry", dashboard_url)


def render() -> None:
    """Render S1's full content (everything except page config).

    Split out from main() so a combined multi-scenario app (see
    demo/unified_app.py) can embed this scenario without a second
    st.set_page_config() call, which Streamlit forbids per session. Standalone
    launches (demo/run_s1.sh) still go through main() below.
    """
    _render_dev_tools_link()
    page_header(
        "S1",
        "Incident Triage & Resolution",
        "Data-quality gate, rule-first + AI triage, routing, similar-incident "
        "retrieval, and RAG resolution drafting — a support engineer reviews "
        "every output before it reaches a ticket, except the quality gate's own "
        "info-request email to the requestor, which is auto-sent.",
    )
    mode = st.radio(
        "Mode",
        ["Triage Funnel", "My Queue", "Batch mode", "Chatbot mode"],
        horizontal=True,
    )
    if mode == "Triage Funnel":
        _triage_funnel_mode()
    elif mode == "Batch mode":
        _batch_mode()
    elif mode == "My Queue":
        _my_queue_mode()
    else:
        _chatbot_mode()


def main() -> None:
    st.set_page_config(page_title="S1 Incident Triage", layout="wide")
    render_login_gate()
    render()


if __name__ == "__main__":
    main()
