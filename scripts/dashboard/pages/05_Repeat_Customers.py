"""Repeat customers — behavioral profiles for users with multiple tickets.

Teaching
--------
This page profiles the small number of users in the 6,728-ticket pool who
filed *more than one* ticket. Each row in ``repeat_user_personas.csv`` is
one customer; the page shows how those customers split into behavioral
profiles and which profiles correlate with poor outcomes.

* **Loading the right CSV.** ``maybe_load_csv(run_dir,
  "repeat_user_personas.csv")`` returns the DataFrame or ``None`` if the
  file doesn't exist; the page prints a friendly warning and stops. This
  is the same defensive load pattern from earlier pages.

* **Code-to-human label dictionary.** ``persona_labels`` maps internal
  snake_case codes (``"creator_channel_operator"``) to display strings
  (``"Creator / channel operator"``). Keeping the mapping right next to
  the page that uses it keeps each page self-contained.

* **``.map(...).fillna(...)`` idiom.**
  ``personas["persona"].map(persona_labels).fillna(personas["persona"])``
  is the safe way to apply a dictionary as a column transformation:
  ``map`` returns ``NaN`` for any code not in the dictionary, and
  ``fillna(...)`` substitutes the original code back in so unrecognised
  values don't disappear. Memorise this pattern — you'll reach for it
  every time you "translate" a column.

* **``value_counts()`` returns a Series, not a DataFrame.**
  ``personas["persona_label"].value_counts()`` produces a Series indexed
  by category with the count as the value. ``counts_df`` (from ``lib``)
  wraps this into a stable two-column DataFrame so charts don't break
  when pandas changes the default column name across versions.

* **``px.histogram(df, x=col, nbins=30)``.** The histogram of tickets-per-
  customer answers "how heavy is the long tail?" — most repeat users have
  2–3 tickets, but a handful have many. Picking ``nbins=30`` controls
  granularity; too few hides shape, too many shows noise.

* **``px.box(df, x=cat, y=num, points="outliers")``.** A boxplot per
  category. ``points="outliers"`` is the key tweak — it draws *only* the
  outlier dots instead of every point, which keeps the chart readable
  with thousands of users. Without it, the boxes would be hidden under a
  cloud of points.

* **Sidebar filter that re-runs the script.** ``min_tickets`` is a slider;
  setting it re-runs the whole module top-to-bottom (Streamlit's mental
  model is "every interaction = re-execute"). The filtered DataFrame ``f``
  is rebuilt from scratch each time. This is *imperative*, not
  declarative — embrace it; the API rewards it.

* **Top-N table.** ``f.sort_values("tickets",
  ascending=False).head(200)`` to display the 200 noisiest repeat users.
  ``ascending=False`` puts the biggest first; ``head(200)`` caps the table
  size so the dashboard doesn't choke on rendering 5,000 rows.

* **Persona breakdown chart.** A horizontal bar of profile counts mirrors
  the leaderboard pattern from page 04. ``yaxis={"categoryorder": "total
  ascending"}`` lets Plotly sort the Y axis by bar length without us
  pre-sorting the DataFrame — a handy alternative to ``sort_values``.

* **Why split the personas at all?** Average metrics across all repeat
  users mask important behaviour: the ``commerce_dispute_or_scam_risk``
  persona will have a very different unresolved-share distribution than
  the ``svip_status_optimizer`` persona. The boxplots are designed to
  surface those gaps so coaching can be targeted.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
from lib import chart_picker, column_cycle, counts_df, density_picker, maybe_load_csv, run_picker

st.title("Repeat customers — behavioral profiles")
st.info(
    "**This page answers:** which users keep coming back, and what do they "
    "keep asking for? Each profile is a behavioural cluster — power users vs "
    "ban appellants vs commerce-dispute risks need different responses.",
    icon=":material/help:",
)
st.caption(
    "Users who filed two or more tickets, grouped by what kind of help they "
    "consistently need. Useful for spotting power users, fairness seekers, "
    "and high-risk commerce users."
)

run_dir = run_picker()
if run_dir is None:
    st.stop()

personas = maybe_load_csv(run_dir, "repeat_user_personas.csv")
if personas is None:
    st.warning("This run does not have `repeat_user_personas.csv`. Run `scripts/insight_layer.py` first.")
    st.stop()

# ---- Friendly persona labels --------------------------------------------

persona_labels = {
    "creator_channel_operator": "Creator / channel operator",
    "commerce_dispute_or_scam_risk": "Commerce dispute or scam risk",
    "repeat_ban_appeal_or_fairness_seeker": "Repeat ban appeal / fairness seeker",
    "general_repeat_user": "Generic repeat user",
    "account_recovery_repeat_user": "Account-recovery repeat user",
    "svip_status_optimizer": "SVIP / status optimizer",
    "multi_problem_power_user": "Multi-problem power user",
}
if "persona" in personas.columns:
    personas = personas.copy()
    personas["persona_label"] = personas["persona"].map(persona_labels).fillna(personas["persona"])

# ---- KPIs ----------------------------------------------------------------

c1, c2, c3, c4 = st.columns(4)
c1.metric("Repeat customers", f"{len(personas):,}")
if "tickets" in personas.columns:
    c2.metric("Total repeat tickets", f"{int(personas['tickets'].sum()):,}")
if "active_days_span" in personas.columns:
    c3.metric("Median active span (days)", f"{personas['active_days_span'].median():.0f}")
if "unresolved_share" in personas.columns:
    c4.metric("Median unresolved %", f"{personas['unresolved_share'].median()*100:.1f}%")

# ---- Persona breakdown --------------------------------------------------

st.subheader("How repeat customers break down")
counts = personas["persona_label"].value_counts() if "persona_label" in personas.columns else pd.Series()
chart_picker(
    counts_df(counts, "Profile", "Customers"),
    label_col="Profile",
    value_col="Customers",
    key_prefix="persona_breakdown",
    default="Horizontal bars",
)

# ---- Filters -------------------------------------------------------------

with st.sidebar:
    st.header("Filters")
    if "persona_label" in personas.columns:
        sel_personas = st.multiselect(
            "Profile", counts.index.tolist(), default=counts.index.tolist()
        )
    else:
        sel_personas = None
    max_personas_tickets = (
        int(personas["tickets"].max()) if "tickets" in personas.columns and len(personas) else 2
    )
    if max_personas_tickets <= 2:
        min_tickets = 2
    else:
        min_tickets = st.slider(
            "Minimum tickets per customer",
            min_value=2,
            max_value=max_personas_tickets,
            value=2,
        )

f = personas.copy()
if sel_personas is not None:
    f = f[f["persona_label"].isin(sel_personas)]
if "tickets" in f.columns:
    f = f[f["tickets"] >= min_tickets]

# ---- Distribution charts (3 stacked) — now in user-chosen layout density --

st.markdown("### Distributions across profiles")
st.caption("Three views of the filtered customer set. Pick how many fit on a row.")
n_cols = density_picker("repeat_distrib", default=2)
next_col = column_cycle(n_cols)

if "tickets" in f.columns and len(f):
    with next_col():
        st.markdown("**Tickets per repeat customer**")
        fig = px.histogram(
            f, x="tickets", nbins=30, height=300,
            labels={"tickets": "Tickets per customer"},
        )
        fig.update_layout(margin=dict(l=10, r=10, t=10, b=10), yaxis_title="Customers")
        st.plotly_chart(fig, use_container_width=True)

if {"persona_label", "unresolved_share"} <= set(f.columns):
    with next_col():
        st.markdown("**Unresolved share, by profile**")
        fig = px.box(
            f, x="persona_label", y="unresolved_share",
            points="outliers", height=300,
            labels={"persona_label": "Profile", "unresolved_share": "Unresolved share"},
        )
        fig.update_layout(margin=dict(l=10, r=10, t=10, b=10))
        fig.update_xaxes(tickangle=-30)
        st.plotly_chart(fig, use_container_width=True)

if {"persona_label", "avg_context_score"} <= set(f.columns):
    with next_col():
        st.markdown("**Note evidence score, by profile**")
        fig = px.box(
            f, x="persona_label", y="avg_context_score",
            points="outliers", height=300,
            labels={"persona_label": "Profile", "avg_context_score": "Avg note evidence score"},
        )
        fig.update_layout(margin=dict(l=10, r=10, t=10, b=10))
        fig.update_xaxes(tickangle=-30)
        st.plotly_chart(fig, use_container_width=True)

# ---- Top repeat users ---------------------------------------------------

st.subheader("Top repeat customers")
rename_map = {
    "uid": "User ID",
    "persona_label": "Profile",
    "tickets": "Tickets",
    "active_days_span": "Active span (days)",
    "first_date": "First ticket",
    "last_date": "Last ticket",
    "unresolved_share": "Unresolved %",
    "avg_context_score": "Avg note evidence score",
    "managers_seen": "Managers seen",
    "top_desires": "Top desires",
    "top_issues": "Top topics",
    "high_context_example_1": "Example ticket",
}
keep = [c for c in rename_map.keys() if c in f.columns]
disp = f.sort_values("tickets", ascending=False)[keep].head(200).copy()
if "unresolved_share" in disp.columns:
    disp["unresolved_share"] = (disp["unresolved_share"] * 100).round(1).astype(str) + "%"
st.dataframe(disp.rename(columns=rename_map), use_container_width=True, hide_index=True, height=520)
