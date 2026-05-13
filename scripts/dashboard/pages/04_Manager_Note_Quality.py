"""How thoroughly each manager documents their tickets.

Compares note quality across managers using a context-evidence score, an
adjusted statistical model (controlling for what each manager handles),
and a coaching checklist.

Teaching
--------
This page asks one question — *"who writes the most thorough notes?"* —
and answers it three different ways on purpose. The reason: any single
ranking can be gamed or biased by the kinds of tickets a manager happens
to handle. If three independent methods all put the same person at the
top, the finding is robust.

* **Three views of the same question.** (1) the *raw* average note-quality
  score per manager; (2) an *OLS-adjusted* delta vs a benchmark manager,
  which subtracts the effect of category mix, status mix, role mix, and
  month; (3) a *non-parametric* residual that compares each manager to the
  average score for their exact ticket cells. Cross-validation: if all
  three rank Albert at the top, the gap is real, not an artefact of one
  modelling choice.

* **Defensive column-list construction.** ``[c for c in rename_map.keys()
  if c in quality.columns]`` builds the display columns from whatever the
  CSV actually contains. New columns added later get picked up automatically;
  missing columns don't crash the page. This pattern shows up everywhere in
  the dashboard.

* **Horizontal bar with sorted Y axis.** ``df.sort_values("avg_context_score",
  ascending=True)`` then a horizontal ``px.bar`` is the canonical recipe
  for a leaderboard. ``ascending=True`` puts the smallest values at the
  bottom of the DataFrame; because Plotly renders Y axis categories from
  bottom to top in row order, the *largest* end up visually at the top.
  Counter-intuitive at first — read the code, then read a chart, and it
  clicks.

* **``px.bar(orientation="h")``.** Horizontal bars make long category
  labels (like full manager names) easy to read; vertical bars would
  rotate the labels and crowd them.

* **Color-by-value bars.** ``color="avg_context_score",
  color_continuous_scale="Blues"`` colors each bar by its own value, which
  reinforces the ranking visually. ``coloraxis_showscale=False`` hides the
  redundant colorbar — the X axis already encodes the same information.

* **Diverging color scale ``"RdBu"``.** For the adjusted-delta chart we want
  red for "below benchmark", blue for "above", and white for "exactly at
  benchmark". ``color_continuous_midpoint=0`` is the critical setting that
  pins white to zero; without it, Plotly maps the midpoint to the data
  median and the chart silently lies. Whenever you draw a residual or a
  delta, use a diverging scale and pin the midpoint.

* **Percent formatting reused.** Just like page 03,
  ``(s * 100).round(1).astype(str) + "%"`` is applied to every column
  ending in ``_share`` before display. Centralising this rule in a list
  comprehension (``[c for c in disp.columns if c.endswith("_share")]``)
  means new ``_share`` columns get formatted automatically.

* **OLS-adjusted delta interpretation.** The ``adjusted_context_delta_vs_baseline``
  column is the coefficient on each manager's dummy variable in a linear
  regression that also includes category, question-kind, role, status, and
  month dummies. In plain English: "after controlling for who handles
  what kind of ticket, how much richer are this manager's notes than the
  benchmark's?" The ``p_value`` and ``model_r2`` columns let a curious
  user sanity-check the fit.

* **Non-parametric robustness.** The residuals view skips the linear model
  entirely: it computes the *average score within each (category,
  question_kind) cell*, subtracts that expected value from each ticket's
  actual score, and averages by manager. If OLS and non-parametric agree,
  the OLS isn't fitting an artefact.

* **Coaching list.** The ``manager_evidence_coaching.csv`` reports per-flag
  rate gaps (e.g. "Albert attaches screenshots 87% of the time vs 41% for
  the benchmark") in a single ``top_evidence_gaps_vs_benchmark`` text
  column. The ``_share`` columns get formatted as percentages and renamed
  by stripping ``has_`` and ``_share``, then prepending ``"% with "`` —
  the rename loop is worth tracing because it's a cute string-manipulation
  recipe.

* **Why bother with three charts?** Cross-validation is the central idea.
  In data science you almost never have one "correct" answer; you have
  several plausible answers and you publish the ones that agree. This
  page is a worked example of that habit.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
from lib import chart_picker, maybe_load_csv, run_picker

# Feature flag: hide manager comparisons unless explicitly enabled.
import settings as _settings
if not getattr(_settings, "SHOW_MANAGER_COMPARISONS", True):
    st.title("Manager note quality")
    st.warning(
        "Manager comparisons are currently disabled. "
        "Ask the dashboard owner to enable this quality-check page when it is needed."
    )
    st.stop()

st.title("Manager note quality")
st.info(
    "**This page answers:** which managers write the most useful tickets, after "
    "controlling for the kinds of cases they handle? Useful for coaching: rich "
    "notes are the raw material every other layer of this analysis depends on.",
    icon=":material/help:",
)
st.caption(
    "Higher scores mean richer notes — more screenshots, IDs, timestamps, "
    "ban reasons, user quotes. The adjusted views below remove the effect of "
    "each manager handling a different mix of tickets."
)

run_dir = run_picker()
if run_dir is None:
    st.stop()

quality = maybe_load_csv(run_dir, "manager_context_quality.csv")
adjusted = maybe_load_csv(run_dir, "adjusted_manager_context_model.csv")
residuals = maybe_load_csv(run_dir, "manager_context_residuals.csv")
coaching = maybe_load_csv(run_dir, "manager_evidence_coaching.csv")

if quality is None:
    st.warning("This run does not have `manager_context_quality.csv` yet.")
    st.stop()

# ---- Top KPIs ------------------------------------------------------------

c1, c2, c3 = st.columns(3)
top_manager = quality.sort_values("avg_context_score", ascending=False).iloc[0]
c1.metric("Top manager (avg score)", top_manager["manager"], f"{top_manager['avg_context_score']:.2f}")
c2.metric("Total managers", len(quality))
if "tickets" in quality.columns:
    c3.metric("Total tickets handled", f"{int(quality['tickets'].sum()):,}")

# ---- Avg context bar chart ----------------------------------------------

st.subheader("Average note evidence score, by manager")
manager_chart_df = (
    quality[["manager", "avg_context_score"]]
    .rename(columns={"manager": "Manager", "avg_context_score": "Note evidence score"})
)
chart_picker(
    manager_chart_df,
    label_col="Manager",
    value_col="Note evidence score",
    key_prefix="manager_avg",
    default="Horizontal bars",
)

# ---- Quality table -------------------------------------------------------

st.subheader("Manager summary")
rename_map = {
    "manager": "Manager",
    "tickets": "Tickets handled",
    "unique_users": "Unique users",
    "avg_context_score": "Avg note evidence score",
    "median_context_score": "Median note evidence score",
    "rich_or_forensic_share": "% rich-evidence notes",
    "image_evidence_share": "% with screenshots",
    "url_share": "% with links",
    "timestamp_share": "% with timestamps",
    "user_claim_share": "% with user quotes",
    "ban_reason_share": "% with ban reasons",
    "unresolved_share": "Unresolved %",
}
cols_to_show = [c for c in rename_map.keys() if c in quality.columns]
disp = quality[cols_to_show].copy()
for col in [c for c in disp.columns if c.endswith("_share")]:
    disp[col] = (disp[col] * 100).round(1).astype(str) + "%"
disp = disp.rename(columns=rename_map)
st.dataframe(disp, width="stretch", hide_index=True, height=380)

# ---- Adjusted model -----------------------------------------------------

if adjusted is not None and "adjusted_context_delta_vs_baseline" in adjusted.columns:
    st.subheader("Adjusted comparison: gap vs benchmark manager")
    st.caption(
        "Positive numbers mean the manager writes richer notes than the benchmark "
        "after accounting for what they actually handle (category, question type, "
        "role, status, month). The benchmark is the alphabetically first manager (Albert)."
    )
    adj_view = st.radio(
        "View as",
        ["Diverging bars", "Lollipop", "Bars only", "Table"],
        horizontal=True,
        key="adjusted_view",
    )
    adj_sorted = adjusted.sort_values("adjusted_context_delta_vs_baseline")
    if adj_view == "Diverging bars":
        fig = px.bar(
            adj_sorted,
            x="adjusted_context_delta_vs_baseline",
            y="manager",
            orientation="h",
            color="adjusted_context_delta_vs_baseline",
            color_continuous_scale="RdBu",
            color_continuous_midpoint=0,
            height=max(360, 28 * len(adjusted)),
            labels={
                "adjusted_context_delta_vs_baseline": "Gap vs benchmark",
                "manager": "Manager",
            },
        )
        fig.update_layout(margin=dict(l=10, r=10, t=10, b=10), coloraxis_showscale=False)
        st.plotly_chart(fig, width="stretch")
    elif adj_view == "Lollipop":
        # Build a lollipop: thin line from 0 to value + a marker at the value.
        import plotly.graph_objects as go
        fig = go.Figure()
        for _, row in adj_sorted.iterrows():
            fig.add_trace(go.Scatter(
                x=[0, row["adjusted_context_delta_vs_baseline"]],
                y=[row["manager"], row["manager"]],
                mode="lines",
                line=dict(color="#9e9e9e", width=2),
                showlegend=False,
                hoverinfo="skip",
            ))
        colors = [
            "#1565c0" if v >= 0 else "#c62828"
            for v in adj_sorted["adjusted_context_delta_vs_baseline"]
        ]
        fig.add_trace(go.Scatter(
            x=adj_sorted["adjusted_context_delta_vs_baseline"],
            y=adj_sorted["manager"],
            mode="markers",
            marker=dict(size=14, color=colors),
            showlegend=False,
            hovertemplate="%{y}<br>Gap vs benchmark: %{x:.2f}<extra></extra>",
        ))
        fig.add_vline(x=0, line_color="#888", line_width=1)
        fig.update_layout(
            height=max(360, 28 * len(adjusted)),
            margin=dict(l=10, r=10, t=10, b=10),
            xaxis_title="Gap vs benchmark",
            yaxis_title="Manager",
            plot_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig, width="stretch")
    elif adj_view == "Bars only":
        fig = px.bar(
            adj_sorted,
            x="adjusted_context_delta_vs_baseline",
            y="manager",
            orientation="h",
            height=max(360, 28 * len(adjusted)),
            labels={
                "adjusted_context_delta_vs_baseline": "Gap vs benchmark",
                "manager": "Manager",
            },
        )
        fig.update_layout(margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig, width="stretch")
    elif adj_view == "Table":
        rename_adj = {
            "manager": "Manager",
            "adjusted_context_delta_vs_baseline": "Gap vs benchmark",
            "baseline_manager": "Benchmark manager",
            "p_value": "p-value",
            "model_r2": "Model R²",
        }
        keep = [c for c in rename_adj.keys() if c in adjusted.columns]
        st.dataframe(adjusted[keep].rename(columns=rename_adj), width="stretch", hide_index=True)

# ---- Non-parametric residuals ------------------------------------------

if residuals is not None and "avg_residual_vs_ticket_mix" in residuals.columns:
    st.subheader("Robustness check: residual vs ticket mix")
    st.caption(
        "Cross-checks the adjusted comparison above using a simpler approach: "
        "subtracts the average score for each manager's exact (category, question type) "
        "cells from their actual score. Same ranking is a positive sign."
    )
    fig = px.bar(
        residuals.sort_values("avg_residual_vs_ticket_mix"),
        x="avg_residual_vs_ticket_mix",
        y="manager",
        orientation="h",
        color="avg_residual_vs_ticket_mix",
        color_continuous_scale="RdBu",
        color_continuous_midpoint=0,
        height=max(360, 28 * len(residuals)),
        labels={"avg_residual_vs_ticket_mix": "Residual", "manager": "Manager"},
    )
    fig.update_layout(margin=dict(l=10, r=10, t=10, b=10), coloraxis_showscale=False)
    st.plotly_chart(fig, width="stretch")
    rename_res = {
        "manager": "Manager",
        "tickets": "Tickets",
        "avg_raw_context": "Raw average score",
        "avg_expected_context": "Expected score for their ticket mix",
        "avg_residual_vs_ticket_mix": "Residual",
        "rich_or_forensic_share": "% rich-evidence notes",
    }
    keep = [c for c in rename_res.keys() if c in residuals.columns]
    disp_r = residuals[keep].copy()
    if "rich_or_forensic_share" in disp_r.columns:
        disp_r["rich_or_forensic_share"] = (disp_r["rich_or_forensic_share"] * 100).round(1).astype(str) + "%"
    st.dataframe(disp_r.rename(columns=rename_res), width="stretch", hide_index=True)

# ---- Evidence coaching --------------------------------------------------

if coaching is not None:
    st.subheader("What each manager could add to reach the benchmark")
    st.caption(
        "Each row lists the evidence types the manager attaches less often than the benchmark. "
        "These are concrete, coachable behaviors — not opinions."
    )
    rename_map_c = {
        "manager": "Manager",
        "tickets": "Tickets",
        "avg_context_score": "Avg note evidence score",
        "rich_or_forensic_share": "% rich-evidence notes",
        "top_evidence_gaps_vs_benchmark": "Biggest gaps vs benchmark",
    }
    show_cols = [c for c in coaching.columns if c in rename_map_c.keys() or c.endswith("_share")]
    disp_c = coaching[show_cols].copy()
    for col in [c for c in disp_c.columns if c.endswith("_share")]:
        disp_c[col] = (disp_c[col] * 100).round(1).astype(str) + "%"
    # Friendly column rename for the *_share columns: drop "_share" and prepend "%"
    final_rename = {**rename_map_c}
    for col in disp_c.columns:
        if col.endswith("_share") and col not in final_rename:
            base = col.replace("has_", "").replace("_share", "").replace("_", " ")
            final_rename[col] = f"% with {base}"
    st.dataframe(disp_c.rename(columns=final_rename), width="stretch", hide_index=True, height=420)
