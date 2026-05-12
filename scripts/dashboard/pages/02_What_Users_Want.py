"""What users actually want — explorer for the discovered want clusters.

Filterable view of the discovered wants and the per-ticket assignments table,
with interactive cross-tabs (want × emotion, want × money risk, want × manager).

Teaching
--------
The structure of this page is "load two CSVs, filter both, render a few
cross-tabs and a drill-down table." The interesting Streamlit/pandas/Plotly
ideas here:

* **Loading two related tables.** ``user_wants_taxonomy.csv`` is one row
  per cluster; ``user_wants_assignments.csv`` is one row per ticket. We
  build a ``title_lookup`` dict from cluster ID to friendly title and
  ``map`` it onto the assignments table so charts can show titles instead
  of raw IDs.

* **Sidebar-driven filters.** The widgets inside ``with st.sidebar:`` mutate
  the local variables ``sel_emotions``, ``money_min`` etc. Each filter then
  conditionally narrows ``filtered = assignments.copy()``. Always start
  from a copy — pandas filtering returns views in some cases and surprises
  you when you mutate later.

* **``pd.crosstab(rows, cols)``** is the "two-dimensional ``value_counts``."
  It produces a DataFrame whose rows are unique values of one column and
  columns are unique values of another, with cell values as the count of
  co-occurrences. It is the standard input shape for a heatmap.

* **``px.imshow(matrix, text_auto=True, color_continuous_scale="Blues")``**
  renders a heatmap directly from a 2D NumPy array (or DataFrame). The
  ``text_auto=True`` flag draws each cell's count on top of the colored
  cell; ``aspect="auto"`` lets cells stretch to fill the figure.

* **``st.tabs([...])``** creates clickable tabbed sections. Inside each
  ``with tab1:`` block you put one tab's worth of content. The user sees a
  row of tab headers and only one tab's body at a time — useful for
  presenting alternative views without scrolling.

* **Adaptive height.** ``height=max(360, 22 * len(ct))`` grows the heatmap
  vertically when there are many rows, but never shrinks below 360px.
  Hard-coded heights make labels overlap; this is a robust compromise.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
from lib import (
    attach_friendly_titles,
    chart_picker,
    counts_df,
    friendly_want_title,
    load_human_labels,
    manager_view_enabled,
    maybe_load_csv,
    run_picker,
)

_SHOW_MANAGERS = manager_view_enabled()

st.title("What users actually want")
st.info(
    "**This page answers:** which goals did users repeatedly come to support with, "
    "in their own words? The list below was discovered from the ticket text, not "
    "from the category column managers fill in.",
    icon=":material/help:",
)
st.caption(
    "These clusters were discovered automatically by reading the rich tickets and "
    "grouping them by what the user was trying to accomplish, not by category labels."
)

run_dir = run_picker()
if run_dir is None:
    st.stop()

taxonomy = maybe_load_csv(run_dir, "user_wants_taxonomy.csv")
assignments = maybe_load_csv(run_dir, "user_wants_assignments.csv")

if taxonomy is None or assignments is None:
    st.warning(
        "This run does not have a discovered taxonomy yet. "
        "Run `scripts/build_user_wants_taxonomy.py outputs/<run_dir>` to generate it."
    )
    st.stop()

human_labels = load_human_labels(run_dir)
taxonomy = attach_friendly_titles(taxonomy, human_labels)
# Mirror the friendly title onto the assignments table by want_id for filters/charts.
title_lookup = dict(zip(taxonomy["want_id"], taxonomy["want_title"]))
if "want_id" in assignments.columns:
    assignments = assignments.copy()
    assignments["want_title"] = assignments["want_id"].map(title_lookup).fillna(
        assignments.get("want_label", "")
    )
elif "want_label" in assignments.columns:
    label_to_title = dict(zip(taxonomy["want_label"], taxonomy["want_title"]))
    assignments = assignments.copy()
    assignments["want_title"] = assignments["want_label"].map(label_to_title).fillna(
        assignments["want_label"]
    )

n_clusters = (taxonomy["want_id"] != -1).sum() if "want_id" in taxonomy.columns else len(taxonomy)
caption_extra = "" if human_labels else " (Run `scripts/label_user_wants.py` to generate friendlier names with a local Ollama model.)"
st.caption(
    f"This run has **{n_clusters}** discovered wants from "
    f"**{len(assignments):,}** tickets read by the local AI.{caption_extra}"
)

# ---- Filters -------------------------------------------------------------

with st.sidebar:
    st.header("Filters")
    if "user_emotion" in assignments.columns:
        emotions = sorted(assignments["user_emotion"].dropna().unique())
        sel_emotions = st.multiselect("User emotion", emotions, default=emotions)
    else:
        sel_emotions = None
    if "money_risk_level" in assignments.columns:
        money_min, money_max = st.slider("Money risk (1 low — 5 high)", 1, 5, (1, 5))
    else:
        money_min, money_max = 1, 5
    if "trust_risk_level" in assignments.columns:
        trust_min, trust_max = st.slider("Trust risk (1 low — 5 high)", 1, 5, (1, 5))
    else:
        trust_min, trust_max = 1, 5
    if "Manager" in assignments.columns:
        managers = sorted(assignments["Manager"].fillna("(unknown)").astype(str).unique())
        sel_managers = st.multiselect("Manager", managers, default=managers)
    else:
        sel_managers = None

filtered = assignments.copy()
if sel_emotions is not None and "user_emotion" in filtered.columns:
    filtered = filtered[filtered["user_emotion"].isin(sel_emotions)]
if "money_risk_level" in filtered.columns:
    filtered = filtered[(filtered["money_risk_level"] >= money_min) & (filtered["money_risk_level"] <= money_max)]
if "trust_risk_level" in filtered.columns:
    filtered = filtered[(filtered["trust_risk_level"] >= trust_min) & (filtered["trust_risk_level"] <= trust_max)]
if sel_managers is not None and "Manager" in filtered.columns:
    filtered = filtered[filtered["Manager"].fillna("(unknown)").astype(str).isin(sel_managers)]

st.metric("Tickets matching filters", f"{len(filtered):,}", delta=f"of {len(assignments):,} total")

# ---- Want size chart -----------------------------------------------------

st.subheader("How many tickets fall into each want")
title_col = "want_title" if "want_title" in filtered.columns else "want_label"
counts = filtered[title_col].value_counts() if title_col in filtered.columns else pd.Series()
if len(counts):
    chart_picker(
        counts_df(counts, "Want", "Tickets"),
        label_col="Want",
        value_col="Tickets",
        key_prefix="want_breakdown",
        default="Horizontal bars",
    )

# ---- Taxonomy table ------------------------------------------------------

st.subheader("Per-want summary")
rename_map = {
    "want_title": "Want",
    "want_summary": "What this cluster is about",
    "size": "Tickets",
    "share": "Share of analyzed tickets",
    "top_jobs": "Top jobs to be done",
    "top_emotions": "Most common emotions",
    "avg_money_risk": "Avg money risk (1-5)",
    "avg_trust_risk": "Avg trust risk (1-5)",
    "avg_urgency": "Avg urgency (1-5)",
    "high_money_risk_share": "Share with high money risk",
    "high_trust_risk_share": "Share with high trust risk",
    "example_1": "Example ticket",
    "next_step_1": "Suggested next step",
    "want_label": "Cluster ID",
}
cols_to_show = [c for c in rename_map.keys() if c in taxonomy.columns]
display_taxonomy = taxonomy[cols_to_show].copy()
for col in ["share", "high_money_risk_share", "high_trust_risk_share"]:
    if col in display_taxonomy.columns:
        display_taxonomy[col] = (display_taxonomy[col] * 100).round(1).astype(str) + "%"
display_taxonomy = display_taxonomy.rename(columns=rename_map)
st.dataframe(display_taxonomy, use_container_width=True, hide_index=True, height=380)

# ---- Cross tabs ----------------------------------------------------------

st.subheader("Cross-tabulations")
tab1, tab2, tab3 = st.tabs(["Want × emotion", "Want × money risk", "Want × manager"])

heat_y_col = "want_title" if "want_title" in filtered.columns else "want_label"

with tab1:
    if "user_emotion" in filtered.columns:
        ct = pd.crosstab(filtered[heat_y_col], filtered["user_emotion"])
        fig = px.imshow(
            ct.values,
            x=ct.columns,
            y=ct.index,
            aspect="auto",
            color_continuous_scale="Blues",
            text_auto=True,
            height=max(360, 22 * len(ct)),
        )
        fig.update_layout(margin=dict(l=10, r=10, t=10, b=10), xaxis_title="Emotion", yaxis_title="Want")
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(ct, use_container_width=True)

with tab2:
    if "money_risk_level" in filtered.columns:
        ct = pd.crosstab(filtered[heat_y_col], filtered["money_risk_level"].astype(int))
        fig = px.imshow(
            ct.values,
            x=[f"Risk {c}" for c in ct.columns],
            y=ct.index,
            aspect="auto",
            color_continuous_scale="Reds",
            text_auto=True,
            height=max(360, 22 * len(ct)),
        )
        fig.update_layout(margin=dict(l=10, r=10, t=10, b=10), xaxis_title="Money risk level", yaxis_title="Want")
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(ct, use_container_width=True)

with tab3:
    if "Manager" in filtered.columns:
        ct = pd.crosstab(filtered[heat_y_col], filtered["Manager"].fillna("(unknown)"))
        fig = px.imshow(
            ct.values,
            x=ct.columns,
            y=ct.index,
            aspect="auto",
            color_continuous_scale="Greens",
            text_auto=True,
            height=max(360, 22 * len(ct)),
        )
        fig.update_layout(margin=dict(l=10, r=10, t=10, b=10), xaxis_title="Manager", yaxis_title="Want")
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(ct, use_container_width=True)
    else:
        st.info("Manager column not available for this run.")

# ---- Per-cluster drill-in -----------------------------------------------

st.subheader("Drill into one want")
drill_col = "want_title" if "want_title" in filtered.columns else "want_label"
labels = sorted(filtered[drill_col].dropna().unique()) if drill_col in filtered.columns else []
if labels:
    chosen = st.selectbox("Want", labels)
    sub = filtered[filtered[drill_col] == chosen].copy()
    st.write(f"**{len(sub)}** tickets match this want under the current filters.")
    show_cols = {
        "source_row": "Ticket #",
        "Manager": "Manager",
        "Date": "Date",
        "Status": "Status",
        "job_to_be_done": "Job to be done",
        "user_emotion": "Emotion",
        "urgency_level": "Urgency",
        "trust_risk_level": "Trust risk",
        "money_risk_level": "Money risk",
        "_want_text": "What user wants (extracted)",
        "support_next_step": "Suggested support step",
        "product_opportunity": "Product opportunity",
        "Question": "Original ticket text",
    }
    keep = [c for c in show_cols if c in sub.columns]
    st.dataframe(
        sub[keep].rename(columns={c: show_cols[c] for c in keep}),
        use_container_width=True,
        hide_index=True,
        height=480,
    )
