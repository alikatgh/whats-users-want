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
full_assignments = maybe_load_csv(run_dir, "user_wants_all_assignments.csv")
enriched = maybe_load_csv(run_dir, "enriched_tickets.csv")

if taxonomy is None or assignments is None:
    st.warning(
        "This run does not have the discovered user-want taxonomy yet. "
        "Choose a completed run that includes the management-ready outputs."
    )
    st.stop()

human_labels = load_human_labels(run_dir)
taxonomy = attach_friendly_titles(taxonomy, human_labels)


def _attach_ticket_context(assignments_df: pd.DataFrame, enriched_df: pd.DataFrame | None) -> pd.DataFrame:
    """Join AI want assignments back to the original ticket context."""
    if (
        enriched_df is None
        or "source_row" not in assignments_df.columns
        or "source_row" not in enriched_df.columns
    ):
        return assignments_df.copy()

    context_cols = [
        "source_row",
        "uid",
        "date",
        "manager",
        "status_en",
        "category",
        "primary_desire",
        "context_depth_band",
        "context_depth_score",
        "question",
        "question_flat",
    ]
    keep = [c for c in context_cols if c in enriched_df.columns]
    context = enriched_df[keep].copy()
    context["_source_row_key"] = context["source_row"].astype(str)
    context = context.drop(columns=["source_row"]).rename(
        columns={
            "uid": "UID",
            "date": "Date",
            "manager": "Manager",
            "status_en": "Status",
            "category": "Category",
            "primary_desire": "Rule-based desire",
            "context_depth_band": "Context depth",
            "context_depth_score": "Context score",
            "question": "Question",
            "question_flat": "Question flat",
        }
    )

    out = assignments_df.copy()
    out["_source_row_key"] = out["source_row"].astype(str)
    out = out.merge(context, on="_source_row_key", how="left")
    return out.drop(columns=["_source_row_key"])


assignments = _attach_ticket_context(assignments, enriched)

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
if full_assignments is not None:
    st.caption(
        f"This run has **{n_clusters}** discovered wants from "
        f"**{len(assignments):,}** tickets read by the local AI, then projected across "
        f"**{len(full_assignments):,}** cleaned tickets."
    )
    st.download_button(
        "Download full-corpus want assignments",
        full_assignments.to_csv(index=False).encode("utf-8"),
        file_name=f"user_wants_all_assignments_{run_dir.name}.csv",
        mime="text/csv",
        icon=":material/download:",
    )
else:
    st.caption(
        f"This run has **{n_clusters}** discovered wants from "
        f"**{len(assignments):,}** tickets read by the local AI."
    )

title_col = "want_title" if "want_title" in assignments.columns else "want_label"

if len(taxonomy):
    sorted_taxonomy = taxonomy.sort_values("size", ascending=False) if "size" in taxonomy.columns else taxonomy
    high_money = (
        taxonomy.sort_values("avg_money_risk", ascending=False).iloc[0]
        if "avg_money_risk" in taxonomy.columns
        else None
    )
    high_trust = (
        taxonomy.sort_values("avg_trust_risk", ascending=False).iloc[0]
        if "avg_trust_risk" in taxonomy.columns
        else None
    )
    c1, c2, c3 = st.columns(3)
    with c1:
        top = sorted_taxonomy.iloc[0]
        st.metric("Largest want", int(top.get("size", 0)))
        st.caption(str(top.get("want_title") or top.get("want_label") or ""))
    with c2:
        if high_money is not None:
            st.metric("Highest money risk", f"{float(high_money.get('avg_money_risk', 0)):.2f}/5")
            st.caption(str(high_money.get("want_title") or high_money.get("want_label") or ""))
    with c3:
        if high_trust is not None:
            st.metric("Highest trust risk", f"{float(high_trust.get('avg_trust_risk', 0)):.2f}/5")
            st.caption(str(high_trust.get("want_title") or high_trust.get("want_label") or ""))

# ---- Filters -------------------------------------------------------------

with st.sidebar:
    st.header("Filters")
    search_query = st.text_input("Search tickets and extracted wants", placeholder="unban, diamonds, voice room...")
    if "job_to_be_done" in assignments.columns:
        jobs = sorted(assignments["job_to_be_done"].dropna().astype(str).unique())
        sel_jobs = st.multiselect("Job to be done", jobs, default=jobs)
    else:
        sel_jobs = None
    if "user_emotion" in assignments.columns:
        emotions = sorted(assignments["user_emotion"].dropna().astype(str).unique())
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
    if _SHOW_MANAGERS and "Manager" in assignments.columns:
        managers = sorted(assignments["Manager"].fillna("(unknown)").astype(str).unique())
        sel_managers = st.multiselect("Manager", managers, default=managers)
    else:
        sel_managers = None
    if "Status" in assignments.columns:
        statuses = sorted(assignments["Status"].fillna("(unknown)").astype(str).unique())
        sel_statuses = st.multiselect("Status", statuses, default=statuses)
    else:
        sel_statuses = None
    if "Category" in assignments.columns:
        categories = sorted(assignments["Category"].fillna("(unknown)").astype(str).unique())
        sel_categories = st.multiselect("Category", categories, default=categories)
    else:
        sel_categories = None

filtered = assignments.copy()
if search_query:
    search_cols = [
        c
        for c in [
            "want_title",
            "_want_text",
            "support_next_step",
            "product_opportunity",
            "Question",
            "Question flat",
            "UID",
        ]
        if c in filtered.columns
    ]
    if search_cols:
        haystack = filtered[search_cols].fillna("").astype(str).agg(" ".join, axis=1)
        filtered = filtered[haystack.str.contains(search_query, case=False, na=False)]
if sel_jobs is not None and "job_to_be_done" in filtered.columns:
    filtered = filtered[filtered["job_to_be_done"].astype(str).isin(sel_jobs)]
if sel_emotions is not None and "user_emotion" in filtered.columns:
    filtered = filtered[filtered["user_emotion"].astype(str).isin(sel_emotions)]
if "money_risk_level" in filtered.columns:
    filtered = filtered[(filtered["money_risk_level"] >= money_min) & (filtered["money_risk_level"] <= money_max)]
if "trust_risk_level" in filtered.columns:
    filtered = filtered[(filtered["trust_risk_level"] >= trust_min) & (filtered["trust_risk_level"] <= trust_max)]
if sel_managers is not None and "Manager" in filtered.columns:
    filtered = filtered[filtered["Manager"].fillna("(unknown)").astype(str).isin(sel_managers)]
if sel_statuses is not None and "Status" in filtered.columns:
    filtered = filtered[filtered["Status"].fillna("(unknown)").astype(str).isin(sel_statuses)]
if sel_categories is not None and "Category" in filtered.columns:
    filtered = filtered[filtered["Category"].fillna("(unknown)").astype(str).isin(sel_categories)]

metric_cols = st.columns(4)
metric_cols[0].metric("Tickets matching filters", f"{len(filtered):,}", delta=f"of {len(assignments):,} total")
visible_wants = filtered[title_col].nunique() if title_col in filtered.columns else 0
metric_cols[1].metric("Visible wants", f"{visible_wants:,}")
if "money_risk_level" in filtered.columns and len(filtered):
    high_money_share = (pd.to_numeric(filtered["money_risk_level"], errors="coerce") >= 4).mean() * 100
    metric_cols[2].metric("High money risk", f"{high_money_share:.1f}%")
else:
    metric_cols[2].metric("High money risk", "—")
if "trust_risk_level" in filtered.columns and len(filtered):
    high_trust_share = (pd.to_numeric(filtered["trust_risk_level"], errors="coerce") >= 4).mean() * 100
    metric_cols[3].metric("High trust risk", f"{high_trust_share:.1f}%")
else:
    metric_cols[3].metric("High trust risk", "—")

# ---- Want size chart -----------------------------------------------------

st.subheader("How many tickets fall into each want")
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
tab_names = ["Want × emotion", "Want × money risk"]
if _SHOW_MANAGERS:
    tab_names.append("Want × manager")
tabs = st.tabs(tab_names)
tab1 = tabs[0]
tab2 = tabs[1]
tab3 = tabs[2] if _SHOW_MANAGERS and len(tabs) > 2 else None

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

if tab3 is not None:
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
        "UID": "UID",
        "Manager": "Manager",
        "Date": "Date",
        "Status": "Status",
        "Category": "Category",
        "Rule-based desire": "Rule-based desire",
        "Context depth": "Context depth",
        "job_to_be_done": "Job to be done",
        "user_emotion": "Emotion",
        "urgency_level": "Urgency",
        "trust_risk_level": "Trust risk",
        "money_risk_level": "Money risk",
        "centroid_similarity": "Cluster confidence",
        "_want_text": "What user wants (extracted)",
        "support_next_step": "Suggested support step",
        "product_opportunity": "Product opportunity",
        "Question": "Original ticket text",
        "Question flat": "Original ticket text",
    }
    if not _SHOW_MANAGERS:
        show_cols.pop("Manager", None)
    keep = [
        c
        for c in show_cols
        if c in sub.columns and not (c == "Question flat" and "Question" in sub.columns)
    ]
    st.dataframe(
        sub[keep].rename(columns={c: show_cols[c] for c in keep}),
        use_container_width=True,
        hide_index=True,
        height=480,
    )
