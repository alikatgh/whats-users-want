"""Executive briefing page for management presentations."""
from __future__ import annotations

import html
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
from lib import (
    attach_friendly_titles,
    discover_extraction_artifacts,
    load_human_labels,
    load_json,
    maybe_load_csv,
    run_picker,
    safe_int,
)


def _job_head(top_jobs: object) -> str:
    if not isinstance(top_jobs, str) or not top_jobs.strip():
        return "other"
    return top_jobs.split(",")[0].split(":")[0].strip() or "other"


def _theme(row: pd.Series) -> str:
    job = _job_head(row.get("top_jobs"))
    label = str(row.get("want_label") or "").lower()
    if job in {"recover_access", "prove_innocence", "understand_punishment"}:
        return "Trust and account recovery"
    if job in {"protect_community", "avoid_scam"}:
        return "Safety, abuse and fraud"
    if job in {"buy_or_sell_diamonds", "restore_income"} or "diamond" in label or "dealer" in label:
        return "Money, diamonds and dealer risk"
    if job in {"restore_visibility", "grow_channel"}:
        return "Visibility and growth"
    if job in {"gain_status"} or "svip" in label:
        return "Status and privileges"
    return "Other operational friction"


def _format_percent(value: object) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "-"


def _panel(title: str, body: str, class_name: str = "wwu-panel") -> None:
    st.markdown(
        f"""
        <div class="{class_name}">
          <h3>{html.escape(title)}</h3>
          <p>{body}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


st.title("Executive briefing")
st.markdown(
    """
    <div class="wwu-eyebrow">Management readout</div>
    <div class="wwu-lede">
    Support tickets are telling us where trust breaks, where money risk
    appears, and which operating changes would reduce repeated escalation.
    </div>
    """,
    unsafe_allow_html=True,
)

run_dir = run_picker("Choose a run to brief")
if run_dir is None:
    st.stop()

taxonomy = maybe_load_csv(run_dir, "user_wants_taxonomy.csv")
assignments = maybe_load_csv(run_dir, "user_wants_assignments.csv")
full_assignments = maybe_load_csv(run_dir, "user_wants_all_assignments.csv")
enriched = maybe_load_csv(run_dir, "enriched_tickets.csv")
run_meta = load_json(str(run_dir), "run_metadata.json") or {}
projection_meta = load_json(str(run_dir), "user_wants_projection_metadata.json") or {}
extraction_info = discover_extraction_artifacts(run_dir)

if taxonomy is None or taxonomy.empty:
    st.warning("This run does not have `user_wants_taxonomy.csv` yet.")
    st.stop()

human_labels = load_human_labels(run_dir)
taxonomy = attach_friendly_titles(taxonomy, human_labels)
taxonomy["theme"] = taxonomy.apply(_theme, axis=1)

rows_in_csv = safe_int(run_meta.get("rows_in_csv"), 0)
clean_rows = safe_int(run_meta.get("rows_enriched"), len(enriched) if enriched is not None else 0)
ai_rows = len(assignments) if assignments is not None else safe_int(extraction_info.get("rows"), 0)
full_rows = len(full_assignments) if full_assignments is not None else 0
wants = int((taxonomy["want_id"] != -1).sum()) if "want_id" in taxonomy.columns else len(taxonomy)
top3_share = float(taxonomy.sort_values("size", ascending=False).head(3)["share"].sum()) if "share" in taxonomy.columns else 0.0

top = taxonomy.sort_values("size", ascending=False).iloc[0]
money_top = taxonomy.sort_values("avg_money_risk", ascending=False).iloc[0] if "avg_money_risk" in taxonomy.columns else top
trust_top = taxonomy.sort_values("avg_trust_risk", ascending=False).iloc[0] if "avg_trust_risk" in taxonomy.columns else top

st.subheader("The one-slide answer")
k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Export rows", f"{rows_in_csv:,}" if rows_in_csv else "-")
k2.metric("Clean tickets", f"{clean_rows:,}" if clean_rows else "-")
k3.metric("AI-read sample", f"{ai_rows:,}")
if full_rows:
    k4.metric("Full corpus mapped", f"{full_rows:,}")
else:
    k4.metric("Top 3 concentration", f"{top3_share * 100:.1f}%")
k5.metric("User wants", f"{wants:,}")

st.markdown(
    f"""
    <div class="wwu-callout wwu-decision">
      <strong>Decision to ask for:</strong> approve three operational workstreams:
      clearer account-ban explanations, a dedicated fraud/diamond escalation lane,
      and separate support playbooks for anxious recovery users versus angry reporting users.
      The evidence is not that users complain randomly; it is that the same few intents repeat.
    </div>
    """,
    unsafe_allow_html=True,
)

col1, col2, col3 = st.columns(3)
with col1:
    _panel(
        "Largest repeated want",
        f"<strong>{html.escape(str(top.get('want_title') or top.get('want_label')))}</strong><br>"
        f"{int(top.get('size', 0))} tickets in the AI-read sample, {_format_percent(top.get('share'))} of analyzed wants.",
    )
with col2:
    _panel(
        "Highest money risk",
        f"<strong>{html.escape(str(money_top.get('want_title') or money_top.get('want_label')))}</strong><br>"
        f"Average money risk {float(money_top.get('avg_money_risk', 0)):.2f}/5.",
    )
with col3:
    _panel(
        "Highest trust risk",
        f"<strong>{html.escape(str(trust_top.get('want_title') or trust_top.get('want_label')))}</strong><br>"
        f"Average trust risk {float(trust_top.get('avg_trust_risk', 0)):.2f}/5.",
    )

st.subheader("What management should remember")
theme_df = (
    taxonomy.groupby("theme", as_index=False)
    .agg(
        tickets=("size", "sum"),
        avg_money_risk=("avg_money_risk", "mean"),
        avg_trust_risk=("avg_trust_risk", "mean"),
        avg_urgency=("avg_urgency", "mean"),
    )
    .sort_values("tickets", ascending=False)
)
theme_total = max(float(theme_df["tickets"].sum()), 1.0)
theme_df["share"] = theme_df["tickets"] / theme_total

readout = theme_df.copy()
readout["Signal"] = readout.apply(
    lambda r: f"{int(r['tickets'])} tickets, {r['share'] * 100:.1f}% of AI-read taxonomy",
    axis=1,
)
readout["Why it matters"] = readout["theme"].map(
    {
        "Trust and account recovery": "Bans, blocks and punishment explanations directly affect retention and perceived fairness.",
        "Safety, abuse and fraud": "Reporting users arrive angry and expect fast visible enforcement.",
        "Money, diamonds and dealer risk": "Money-linked disputes are lower volume but higher trust risk.",
        "Visibility and growth": "Creators and groups see recommendation loss as platform punishment.",
        "Status and privileges": "SVIP/status issues carry reputational sensitivity even when volume is smaller.",
        "Other operational friction": "Mixed issues worth monitoring but not the first investment lane.",
    }
)
readout["Recommended management move"] = readout["theme"].map(
    {
        "Trust and account recovery": "Fund clearer ban reason templates, appeal status tracking and recovery macros.",
        "Safety, abuse and fraud": "Create a reporting triage playbook with evidence checklist and response SLAs.",
        "Money, diamonds and dealer risk": "Create a fraud/diamond escalation lane with transaction evidence standards.",
        "Visibility and growth": "Give support a visibility diagnostic and a clear explanation script.",
        "Status and privileges": "Route SVIP/status disputes through a tighter verification path.",
        "Other operational friction": "Keep in monitoring; do not lead the roadmap with it.",
    }
)
show = readout[["theme", "Signal", "Why it matters", "Recommended management move"]].rename(
    columns={"theme": "Business theme"}
)
st.dataframe(show, use_container_width=True, hide_index=True, height=290)

st.subheader("Evidence shape")
chart_col, risk_col = st.columns([1.15, 1])
with chart_col:
    top_wants = taxonomy.sort_values("size", ascending=False).head(10).copy()
    top_wants["Share"] = top_wants["share"] * 100 if "share" in top_wants.columns else 0
    fig = px.bar(
        top_wants.sort_values("size", ascending=True),
        x="size",
        y="want_title",
        color="theme",
        orientation="h",
        labels={"size": "Tickets", "want_title": "User want", "theme": "Theme"},
        color_discrete_sequence=["#1f5eff", "#007f7a", "#a35b00", "#475569", "#7c3aed", "#64748b"],
        height=430,
    )
    fig.update_layout(margin=dict(l=10, r=10, t=10, b=10), showlegend=False)
    st.plotly_chart(fig, use_container_width=True)

with risk_col:
    risk = taxonomy.copy()
    risk["Ticket volume"] = risk["size"]
    fig = px.scatter(
        risk,
        x="avg_money_risk",
        y="avg_trust_risk",
        size="Ticket volume",
        color="theme",
        hover_name="want_title",
        labels={
            "avg_money_risk": "Avg money risk",
            "avg_trust_risk": "Avg trust risk",
            "theme": "Theme",
        },
        color_discrete_sequence=["#1f5eff", "#007f7a", "#a35b00", "#475569", "#7c3aed", "#64748b"],
        height=430,
    )
    fig.update_layout(margin=dict(l=10, r=10, t=10, b=10), legend=dict(orientation="h", y=-0.2))
    st.plotly_chart(fig, use_container_width=True)

st.subheader("How to present the caveat")
if full_rows:
    st.markdown(
        f"""
        <div class="wwu-callout">
          <strong>Method note:</strong> the base pipeline cleaned and clustered
          {clean_rows:,} tickets from {rows_in_csv:,} source rows. The richer
          Mistral/Ollama extraction deeply read {ai_rows:,} risk-balanced tickets,
          discovered {wants} user wants, then the projection stage mapped
          {full_rows:,} cleaned tickets onto those wants with confidence bands.
          Rows marked low-confidence remain a targeted review queue, not an
          overclaimed model decision.
        </div>
        """,
        unsafe_allow_html=True,
    )
else:
    st.markdown(
        f"""
        <div class="wwu-callout">
          <strong>Method note:</strong> the base pipeline cleaned and clustered
          {clean_rows:,} tickets from {rows_in_csv:,} source rows. The richer
          Mistral/Ollama extraction read {ai_rows:,} risk-balanced tickets and
          produced the {wants} want clusters shown here. Treat this as a strong
          decision sample, not yet a full LLM census of every ticket.
        </div>
        """,
        unsafe_allow_html=True,
    )

download = show.copy()
download["Run"] = run_dir.name
download["AI model"] = str(extraction_info.get("model") or "")
download["Full corpus mapped"] = full_rows
download["Projection threshold"] = projection_meta.get("assignment_threshold", "")
st.download_button(
    "Download management readout CSV",
    download.to_csv(index=False).encode("utf-8"),
    file_name=f"management_readout_{run_dir.name}.csv",
    mime="text/csv",
    icon=":material/download:",
)
