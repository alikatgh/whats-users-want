"""Opportunities ranked by impact.

Ranks every discovered topic by an impact score combining ticket volume,
unresolved share, recent growth, and trust/money risk.

Teaching
--------
This page is a *prioritisation tool*: it takes every topic discovered across
the 6,728 tickets and helps a human pick where to invest next. The page
filters and ranks topics by an impact score combining size, unresolved share,
recent lift, and trust/money risk. Walk through the moving parts:

* **Two-CSV fallback.** ``maybe_load_csv(run_dir,
  "refined_opportunity_backlog.csv")`` returns ``None`` when the refined
  version isn't present, so we then try ``opportunity_backlog.csv``. The
  caption tells the user which one they're looking at. This "prefer the
  better artifact, fall back to the basic one" pattern keeps the dashboard
  useful even on partial runs.

* **Sidebar pattern.** Every widget inside ``with st.sidebar:`` mutates a
  local variable (``sel_actions``, ``min_tickets``, ``min_unresolved``…)
  that the body of the page uses to narrow the DataFrame ``f``. Each
  widget is one filter; reading the sidebar top-to-bottom tells you the
  full set of knobs.

* **``st.slider(label, min, max, default, step)``.** A range filter widget.
  ``st.slider("Minimum unresolved share", 0.0, 1.0, 0.0, step=0.05)``
  produces a 0.0–1.0 slider with 5-percent ticks; the user's choice comes
  back as a single float. When you pass a tuple as default, you get a
  two-handle range slider instead.

* **Sort-by mapping.** ``sort_options = {"opportunity_score": "Impact score",
  ...}`` keeps an internal column name on the left and a friendly label on
  the right. The ``st.selectbox`` shows the labels; the
  ``next(k for k, v in sort_options.items() if v == sort_by_label)`` line
  resolves the choice back to the column name. Same trick is used for the
  desire dropdown on other pages.

* **``df.sort_values(col, ascending=False).head(50)``.** This is the canonical
  "give me the top N rows by a metric" idiom. ``head(50)`` after the sort
  materialises the leaderboard for the bubble chart — drawing all topics
  would clutter the plot.

* **``px.scatter`` for a bubble chart.** ``size="Tickets"`` makes each
  bubble's area proportional to ticket volume; ``color="Trust / money
  risk"`` maps the column onto a continuous color scale; ``log_x=True``
  switches the X axis to log-scale, which is essential for the long-tailed
  ticket-count distribution (a few topics with thousands of tickets, lots
  with under ten); ``hover_name=`` controls the tooltip header;
  ``hover_data={col: True}`` opts specific columns *into* the tooltip
  without affecting the plotted geometry.

* **``st.subheader``.** Renders a section header. Pages typically alternate
  ``st.subheader`` + caption + chart/table to give the eye a rhythm.

* **``st.dataframe(df, use_container_width=True, hide_index=True,
  height=520)``.** ``use_container_width=True`` stretches the table to the
  full column; ``hide_index=True`` removes the pandas integer index (which
  is meaningless to a non-coder); ``height=520`` pins a comfortable scroll
  area instead of letting the table grow indefinitely.

* **Friendly column names.** ``rename_map`` keeps internal snake_case
  column names in the DataFrame (so the rest of the code stays terse) but
  presents human labels (``"Tickets in last 30 days"``) at display time.
  This separation is worth internalising — never hand the user raw
  ``recent_lift`` text.

* **Percent formatting.** ``(s * 100).round(1).astype(str) + "%"`` casts a
  probability column to a display string like ``"73.4%"``. We do this on
  ``unresolved_share``, ``rich_or_forensic_share``, and ``trust_money_risk``
  before handing them to ``st.dataframe``. Note the order: multiply, round,
  cast, concatenate.

* **Drill-down pattern.** A ``st.selectbox(... labels[:200])`` picks a
  single topic; ``f[f["issue_label"] == chosen]`` re-filters; we read
  ``row.get("recommended_action", "")`` and pull example tickets into
  three columns. This is the typical "summary up top, detail below"
  Streamlit layout.

* **Optional emerging-topics overlay.** The bottom section is wrapped in
  ``if emerging is not None and "last_30_tickets" in emerging.columns``.
  Defensive checks like this are how we keep one page working across many
  different run snapshots.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
from lib import maybe_load_csv, run_picker, counts_df, chart_picker

st.title("Opportunities ranked by impact")
st.info(
    "**This page answers:** which problems should the team fix first? Topics are "
    "scored by ticket volume, unresolved share, recent growth, and whether trust "
    "or money is at stake. The top of the list deserves the next product or "
    "support investment.",
    icon=":material/help:",
)
st.caption(
    "Each row is a discovered topic. The impact score combines how many "
    "tickets the topic represents, how often they go unresolved, whether "
    "volume is growing, and whether trust or money is at stake."
)

run_dir = run_picker()
if run_dir is None:
    st.stop()

refined = maybe_load_csv(run_dir, "refined_opportunity_backlog.csv")
original = maybe_load_csv(run_dir, "opportunity_backlog.csv")
emerging = maybe_load_csv(run_dir, "emerging_topics.csv")

if refined is None and original is None:
    st.warning(
        "This run does not include an opportunity backlog yet. "
        "Choose a completed run with opportunity outputs to view this page."
    )
    st.stop()

source = "refined backlog (with outlier sub-themes)" if refined is not None else "original backlog"
df = refined if refined is not None else original
assert df is not None
st.caption(f"Showing the **{source}** — {len(df):,} topics.")

# ---- Filters -------------------------------------------------------------

with st.sidebar:
    st.header("Filters")
    if "recommended_action" in df.columns:
        actions = sorted(df["recommended_action"].dropna().unique())
        sel_actions = st.multiselect("Recommended action", actions, default=actions)
    else:
        sel_actions = None
    if "tickets" in df.columns:
        min_tickets = st.slider("Minimum tickets in topic", 0, int(df["tickets"].max()) + 1, 0)
    else:
        min_tickets = 0
    if "unresolved_share" in df.columns:
        min_unresolved = st.slider("Minimum unresolved share", 0.0, 1.0, 0.0, step=0.05)
    else:
        min_unresolved = 0.0
    if "trust_money_risk" in df.columns:
        min_risk = st.slider("Minimum trust / money risk", 0.0, 1.0, 0.0, step=0.05)
    else:
        min_risk = 0.0
    if "recent_lift" in df.columns:
        min_lift = st.slider("Minimum recent vs baseline ratio", 0.0, float(df["recent_lift"].max()) + 0.1, 0.0, step=0.1)
    else:
        min_lift = 0.0
    sort_options = {
        "opportunity_score": "Impact score",
        "tickets": "Tickets",
        "unresolved_share": "Unresolved share",
        "recent_lift": "Recent vs baseline",
        "trust_money_risk": "Trust / money risk",
    }
    sort_options = {k: v for k, v in sort_options.items() if k in df.columns}
    sort_by_label = st.selectbox("Sort by", list(sort_options.values()))
    sort_by = next(k for k, v in sort_options.items() if v == sort_by_label)

f = df.copy()
if sel_actions is not None and "recommended_action" in f.columns:
    f = f[f["recommended_action"].isin(sel_actions)]
if "tickets" in f.columns:
    f = f[f["tickets"] >= min_tickets]
if "unresolved_share" in f.columns:
    f = f[f["unresolved_share"] >= min_unresolved]
if "trust_money_risk" in f.columns:
    f = f[f["trust_money_risk"] >= min_risk]
if "recent_lift" in f.columns:
    f = f[f["recent_lift"] >= min_lift]
f = f.sort_values(sort_by, ascending=False)

# ---- KPIs ----------------------------------------------------------------

kpi1, kpi2, kpi3, kpi4 = st.columns(4)
kpi1.metric("Topics shown", f"{len(f):,}", f"of {len(df):,}")
if "tickets" in f.columns:
    kpi2.metric("Tickets covered", f"{int(f['tickets'].sum()):,}")
if "unresolved_share" in f.columns and len(f):
    kpi3.metric("Avg unresolved share", f"{f['unresolved_share'].mean()*100:.1f}%")
if "trust_money_risk" in f.columns and len(f):
    kpi4.metric("Avg trust / money risk", f"{f['trust_money_risk'].mean():.2f}")

# ---- Topic landscape — multi-view --------------------------------------

st.subheader("Topic landscape")
st.caption(
    "Pick how to look at the top 50 topics. Bubble = volume vs impact, "
    "treemap = relative size by impact, donut = how recommended actions split."
)
if {"opportunity_score", "tickets"} <= set(f.columns):
    plot_df = f.head(50).rename(
        columns={
            "opportunity_score": "Impact score",
            "tickets": "Tickets",
            "trust_money_risk": "Trust / money risk",
            "unresolved_share": "Unresolved share",
            "recent_lift": "Recent vs baseline",
            "recommended_action": "Recommended action",
            "issue_label": "Topic",
        }
    )
    landscape_view = st.radio(
        "View as",
        ["Bubble chart", "Treemap by impact", "Donut by recommended action", "Bar by impact", "Table"],
        horizontal=True,
        key="landscape_view",
    )
    if landscape_view == "Bubble chart":
        fig = px.scatter(
            plot_df,
            x="Tickets",
            y="Impact score",
            size="Tickets",
            color="Trust / money risk" if "Trust / money risk" in plot_df.columns else None,
            hover_name="Topic" if "Topic" in plot_df.columns else None,
            hover_data={
                c: True
                for c in ["Unresolved share", "Recent vs baseline", "Recommended action"]
                if c in plot_df.columns
            },
            log_x=True,
            height=460,
            color_continuous_scale="Reds",
        )
        fig.update_layout(margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)
    elif landscape_view == "Treemap by impact":
        fig = px.treemap(
            plot_df,
            path=["Topic"],
            values="Impact score",
            color="Trust / money risk" if "Trust / money risk" in plot_df.columns else None,
            color_continuous_scale="Reds",
            height=520,
        )
        fig.update_layout(margin=dict(l=10, r=10, t=10, b=10))
        fig.update_traces(textinfo="label+value")
        st.plotly_chart(fig, use_container_width=True)
    elif landscape_view == "Donut by recommended action":
        if "Recommended action" in plot_df.columns:
            action_counts = plot_df["Recommended action"].value_counts()
            adf = counts_df(action_counts, "Recommended action", "Topics")
            fig = px.pie(adf, names="Recommended action", values="Topics", hole=0.55, height=520)
            fig.update_traces(textposition="outside", textinfo="label+percent")
            fig.update_layout(margin=dict(l=10, r=10, t=10, b=10), showlegend=False)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Recommended actions not present in this run.")
    elif landscape_view == "Bar by impact":
        adf = plot_df[["Topic", "Impact score"]].sort_values("Impact score", ascending=False)
        fig = px.bar(adf, x="Impact score", y="Topic", orientation="h",
                     height=max(380, 18 * len(adf)))
        fig.update_layout(margin=dict(l=10, r=10, t=10, b=10),
                          yaxis={"categoryorder": "total ascending"})
        st.plotly_chart(fig, use_container_width=True)
    elif landscape_view == "Table":
        cols = [c for c in ["Topic", "Tickets", "Impact score", "Unresolved share",
                            "Trust / money risk", "Recent vs baseline", "Recommended action"]
                if c in plot_df.columns]
        st.dataframe(plot_df[cols], use_container_width=True, hide_index=True, height=520)

# ---- Backlog table -------------------------------------------------------

st.subheader("Ranked list")
rename_map = {
    "issue_label": "Topic",
    "tickets": "Tickets",
    "unique_users": "Unique users",
    "unresolved_share": "Unresolved %",
    "rich_or_forensic_share": "% with rich evidence",
    "trust_money_risk": "Trust / money risk",
    "urgency_avg": "Avg urgency",
    "recent_tickets": "Tickets in last 30 days",
    "recent_lift": "Recent vs baseline",
    "trend_z": "Trend strength",
    "opportunity_score": "Impact score",
    "recommended_action": "Recommended action",
    "top_desires": "Top user desires",
    "top_managers": "Top managers",
}
cols_to_show = [c for c in rename_map.keys() if c in f.columns]
display = f[cols_to_show].copy()
for col in ["unresolved_share", "rich_or_forensic_share", "trust_money_risk"]:
    if col in display.columns:
        display[col] = (display[col] * 100).round(1).astype(str) + "%"
display = display.rename(columns=rename_map)
st.dataframe(display, use_container_width=True, hide_index=True, height=520)

# ---- Drill into one topic -----------------------------------------------

st.subheader("Drill into one topic")
labels = sorted(f["issue_label"].dropna().unique()) if "issue_label" in f.columns else []
if labels:
    chosen = st.selectbox("Topic", labels[:200])
    sub = f[f["issue_label"] == chosen]
    if len(sub):
        row = sub.iloc[0]
        st.write(f"**Recommended action:** {row.get('recommended_action', '')}")
        ec1, ec2, ec3 = st.columns(3)
        for col, ex in zip([ec1, ec2, ec3], ["example_1", "example_2", "example_3"]):
            if ex in sub.columns:
                col.write(f"**Example ticket**\n\n{sub.iloc[0].get(ex, '')}")

# ---- Emerging topics overlay --------------------------------------------

st.subheader("Topics growing in the last 30 days")
if emerging is not None and "last_30_tickets" in emerging.columns:
    em = emerging[emerging["last_30_tickets"] >= 5].head(20).copy()
    em_rename = {
        "issue_label": "Topic",
        "last_30_tickets": "Tickets in last 30 days",
        "recent_vs_prior_lift": "Recent vs prior ratio",
        "recent_vs_prior_z": "Trend strength",
        "recent_unresolved_share": "Unresolved % (last 30 days)",
        "emergence_score": "Emergence score",
        "top_desires": "Top user desires",
    }
    keep = [c for c in em_rename.keys() if c in em.columns]
    em_disp = em[keep].copy()
    if "recent_unresolved_share" in em_disp.columns:
        em_disp["recent_unresolved_share"] = (em_disp["recent_unresolved_share"] * 100).round(1).astype(str) + "%"
    em_disp = em_disp.rename(columns=em_rename)
    st.dataframe(em_disp, use_container_width=True, hide_index=True)
else:
    st.info("Emerging topics table not found in this run.")
