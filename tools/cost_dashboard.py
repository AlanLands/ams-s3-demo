"""Internal LLM cost/usage dashboard — NOT part of the client demo.

Reads the telemetry log every `common.llm.complete()` call writes (across all
scenarios, S1 today, S2-S6 automatically once they call `complete()`) and shows
call volume, cache-hit rate, token usage, and latency, broken down by scenario.

Run: streamlit run tools/cost_dashboard.py
"""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from common.telemetry import cache_hit_rate, read_calls, summarize_by_scenario

# Categorical slots 1 (blue) and 2 (green) from the project's validated palette —
# only 2 series ever appear on one chart here, well under the CVD-safety cap.
_PALETTE = {
    "light": {"live": "#2a78d6", "cached": "#008300"},
    "dark": {"live": "#3987e5", "cached": "#008300"},
}


def _mode() -> str:
    return "dark" if st.get_option("theme.base") == "dark" else "light"


def _kpi_row(calls: list[dict]) -> None:
    hit_rate = cache_hit_rate(calls)
    total = len(calls)
    live = sum(1 for c in calls if not c["cached"])
    cached = total - live
    input_tokens = sum(c.get("input_tokens") or 0 for c in calls)
    output_tokens = sum(c.get("output_tokens") or 0 for c in calls)

    cols = st.columns(5)
    cols[0].metric("Total calls", total)
    cols[1].metric("Live calls", live)
    cols[2].metric("Cache hits", cached, help="Calls avoided by hitting .cache/llm")
    cols[3].metric("Cache hit rate", f"{hit_rate:.0%}" if hit_rate is not None else "—")
    cols[4].metric("Input+output tokens", f"{input_tokens + output_tokens:,}")


def _calls_by_scenario_chart(calls: list[dict]) -> alt.Chart:
    df = pd.DataFrame(calls)
    df["kind"] = df["cached"].map({True: "cached", False: "live"})
    grouped = df.groupby(["scenario", "kind"]).size().reset_index(name="count")
    colors = _PALETTE[_mode()]
    color_range = [colors["live"], colors["cached"]]
    return (
        alt.Chart(grouped)
        .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
        .encode(
            x=alt.X("scenario:N", title="Scenario"),
            y=alt.Y("count:Q", title="Calls"),
            color=alt.Color(
                "kind:N",
                title="Call type",
                scale=alt.Scale(domain=["live", "cached"], range=color_range),
            ),
            tooltip=["scenario", "kind", "count"],
        )
        .properties(height=280)
    )


def _tokens_by_scenario_chart(summaries) -> alt.Chart:
    rows = []
    for s in summaries:
        rows.append({"scenario": s.scenario, "kind": "input", "tokens": s.input_tokens})
        rows.append({"scenario": s.scenario, "kind": "output", "tokens": s.output_tokens})
    df = pd.DataFrame(rows)
    colors = _PALETTE[_mode()]
    color_range = [colors["live"], colors["cached"]]
    return (
        alt.Chart(df)
        .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
        .encode(
            x=alt.X("scenario:N", title="Scenario"),
            y=alt.Y("tokens:Q", title="Tokens (live calls only)"),
            color=alt.Color(
                "kind:N",
                title="Token type",
                scale=alt.Scale(domain=["input", "output"], range=color_range),
            ),
            tooltip=["scenario", "kind", "tokens"],
        )
        .properties(height=280)
    )


def _latency_chart(summaries) -> alt.Chart:
    rows = []
    for s in summaries:
        if s.avg_live_latency_s is not None:
            rows.append({"scenario": s.scenario, "kind": "live", "seconds": s.avg_live_latency_s})
        if s.avg_cached_latency_s is not None:
            rows.append(
                {"scenario": s.scenario, "kind": "cached", "seconds": s.avg_cached_latency_s}
            )
    df = pd.DataFrame(rows)
    colors = _PALETTE[_mode()]
    color_range = [colors["live"], colors["cached"]]
    return (
        alt.Chart(df)
        .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
        .encode(
            x=alt.X("scenario:N", title="Scenario"),
            xOffset="kind:N",
            y=alt.Y("seconds:Q", title="Avg latency (s)"),
            color=alt.Color(
                "kind:N",
                title="Call type",
                scale=alt.Scale(domain=["live", "cached"], range=color_range),
            ),
            tooltip=["scenario", "kind", alt.Tooltip("seconds:Q", format=".2f")],
        )
        .properties(height=280)
    )


def main() -> None:
    st.set_page_config(page_title="LLM cost & usage telemetry", layout="wide")
    st.title("LLM cost & usage telemetry")
    st.caption(
        "Internal tool — not part of the client demo. Reads every `common.llm.complete()` "
        "call across all scenarios; covers S1 now, S2-S6 automatically as they land."
    )

    calls = read_calls()
    if not calls:
        st.info("No telemetry yet — run any scenario's app or smoke script to generate calls.")
        return

    summaries = summarize_by_scenario(calls)
    if all(s.estimated_cost_usd is None for s in summaries):
        st.warning(
            "Cost estimates are unset — `common/telemetry.py:MODEL_PRICING_USD_PER_1M` has no "
            "rates configured, so token counts below are real but dollar costs are not shown. "
            "Fill in real per-model rates to enable cost totals."
        )

    _kpi_row(calls)

    st.subheader("Calls by scenario")
    st.altair_chart(_calls_by_scenario_chart(calls), use_container_width=True)

    st.subheader("Tokens by scenario")
    st.altair_chart(_tokens_by_scenario_chart(summaries), use_container_width=True)

    st.subheader("Latency: cached vs. live")
    st.altair_chart(_latency_chart(summaries), use_container_width=True)

    st.subheader("Summary by scenario")
    st.dataframe(
        [
            {
                "scenario": s.scenario,
                "total_calls": s.total_calls,
                "live_calls": s.live_calls,
                "cached_calls": s.cached_calls,
                "input_tokens": s.input_tokens,
                "output_tokens": s.output_tokens,
                "avg_live_latency_s": (
                    round(s.avg_live_latency_s, 2) if s.avg_live_latency_s is not None else None
                ),
                "avg_cached_latency_s": (
                    round(s.avg_cached_latency_s, 2) if s.avg_cached_latency_s is not None else None
                ),
                "estimated_cost_usd": s.estimated_cost_usd,
            }
            for s in summaries
        ],
        use_container_width=True,
    )

    st.subheader("Recent calls")
    recent = sorted(calls, key=lambda c: c["ts"], reverse=True)[:100]
    st.dataframe(pd.DataFrame(recent), use_container_width=True, height=300)


if __name__ == "__main__":
    main()
