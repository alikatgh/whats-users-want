"""Macro/micro longitudinal readout for management.

This page is deliberately not another count chart. It visualizes the layer that
spreadsheets do not produce by default: change over time, a simple next-month
early warning, and repeat-user journeys where one UID keeps coming back with a
sequence of related or escalating problems.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
from lib import load_json, maybe_load_csv, run_picker, safe_float, safe_int


def _clean(value: object, fallback: str = "-") -> str:
    text = str(value or "").strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return fallback
    return text


def _pct(value: object) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "-"


def _unique_want_titles(df: pd.DataFrame, title_col: str = "want_title") -> pd.Series:
    """Make duplicate human labels distinguishable without exposing raw labels first."""
    if df.empty or title_col not in df.columns:
        return pd.Series(dtype=str)
    ids = df.get("assigned_want_id")
    if ids is None:
        ids = df.get("want_id", pd.Series(range(len(df)), index=df.index))
    title_counts = df.groupby(title_col)[ids.name].nunique() if ids.name in df.columns else df[title_col].value_counts()

    def _label(row: pd.Series) -> str:
        title = _clean(row.get(title_col))
        duplicate = title_counts.get(title, 0) > 1
        if duplicate:
            return f"{title} · cluster {int(row.get(ids.name, 0))}"
        return title

    tmp = df.copy()
    if ids.name not in tmp.columns:
        tmp[ids.name] = ids
    return tmp.apply(_label, axis=1)


def _status_color(status: object) -> str:
    status_l = _clean(status, "").lower()
    if status_l in {"closed", "done", "resolved"}:
        return "#0f9f6e"
    if status_l in {"failed", "no action"}:
        return "#d64545"
    if status_l in {"in process", "open"}:
        return "#b7791f"
    return "#64748b"


def _build_assignment_audit(full_assignments: pd.DataFrame | None) -> pd.DataFrame:
    """Prepare the full-corpus assignment table for method/audit drill-downs."""
    if full_assignments is None or full_assignments.empty:
        return pd.DataFrame()
    audit = full_assignments.copy()
    if "assigned_want_id" in audit.columns:
        audit["assigned_want_id"] = pd.to_numeric(audit["assigned_want_id"], errors="coerce").astype("Int64")
    audit["display_want"] = _unique_want_titles(audit)
    if "date_raw" in audit.columns:
        audit["date_for_audit"] = pd.to_datetime(audit["date_raw"], errors="coerce", dayfirst=True)
    elif "date" in audit.columns:
        audit["date_for_audit"] = pd.to_datetime(audit["date"], errors="coerce")
    else:
        audit["date_for_audit"] = pd.NaT
    audit["month"] = audit["date_for_audit"].dt.to_period("M").astype(str)
    return audit


st.title("Macro and micro reality")
st.markdown(
    """
    <div class="wwu-eyebrow">Timeline, forecast, and user journeys</div>
    <div class="wwu-lede">
    This page is the answer to “why did we use a GPU?” It turns the model-derived
    user-want layer into time trends, early-warning signals, and UID-level
    histories that show how users actually move through repeated problems.
    </div>
    """,
    unsafe_allow_html=True,
)

run_dir = run_picker("Choose a run to inspect")
if run_dir is None:
    st.stop()

metadata = load_json(str(run_dir), "longitudinal_metadata.json") or {}
monthly = maybe_load_csv(run_dir, "longitudinal_want_monthly_trends.csv")
emerging = maybe_load_csv(run_dir, "longitudinal_emerging_wants.csv")
journeys = maybe_load_csv(run_dir, "longitudinal_user_journeys.csv")
events = maybe_load_csv(run_dir, "longitudinal_user_journey_events.csv")
archetypes = maybe_load_csv(run_dir, "longitudinal_journey_archetypes.csv")
full_assignments = maybe_load_csv(run_dir, "user_wants_all_assignments.csv")

missing = [
    name
    for name, df in [
        ("longitudinal_want_monthly_trends.csv", monthly),
        ("longitudinal_emerging_wants.csv", emerging),
        ("longitudinal_user_journeys.csv", journeys),
        ("longitudinal_user_journey_events.csv", events),
        ("longitudinal_journey_archetypes.csv", archetypes),
    ]
    if df is None
]
if missing:
    st.warning(
        "This run does not have the longitudinal layer yet. Generate it once, then refresh the dashboard."
    )
    st.code(f"python scripts/build_longitudinal_insights.py {run_dir}", language="bash")
    st.caption("Missing files: " + ", ".join(missing))
    st.stop()

assert monthly is not None
assert emerging is not None
assert journeys is not None
assert events is not None
assert archetypes is not None

complete_months = metadata.get("complete_months") or sorted(monthly["month"].dropna().astype(str).unique().tolist())
records = safe_int(metadata.get("records"), 0)
repeat_users = safe_int(metadata.get("repeat_users"), len(journeys))
repeat_users_3 = safe_int(metadata.get("repeat_users_3_plus"), int((journeys["records"] >= 3).sum()) if "records" in journeys.columns else 0)
journey_events = safe_int(metadata.get("journey_events"), len(events))

monthly = monthly.copy()
emerging = emerging.copy()
journeys = journeys.copy()
events = events.copy()
archetypes = archetypes.copy()
assignment_audit = _build_assignment_audit(full_assignments)

monthly["display_want"] = _unique_want_titles(monthly)
emerging["display_want"] = _unique_want_titles(emerging)
monthly["month_date"] = pd.to_datetime(monthly["month"].astype(str) + "-01", errors="coerce")
for col in ["records", "unique_users", "failed_or_open_share", "review_queue_share"]:
    if col in monthly.columns:
        monthly[col] = pd.to_numeric(monthly[col], errors="coerce").fillna(0)
for col in [
    "recent_records",
    "prior_records",
    "growth_ratio",
    "monthly_slope",
    "forecast_next_month",
    "momentum_score",
    "recent_failed_or_open_share",
    "recent_review_queue_share",
]:
    if col in emerging.columns:
        emerging[col] = pd.to_numeric(emerging[col], errors="coerce").fillna(0)

top_momentum = emerging.sort_values(["momentum_score", "recent_records"], ascending=False).iloc[0]
top_archetype = archetypes.sort_values("records", ascending=False).iloc[0] if len(archetypes) else None

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Mapped records", f"{records:,}")
k2.metric("Complete months", f"{len(complete_months)}", delta=f"{complete_months[0]} to {complete_months[-1]}" if complete_months else None)
k3.metric("Repeat users", f"{repeat_users:,}", delta=f"{repeat_users_3:,} with 3+ records")
k4.metric("Journey events", f"{journey_events:,}")
k5.metric("Top early warning", _clean(top_momentum.get("display_want")), delta=f"{safe_float(top_momentum.get('forecast_next_month')):.1f} next-month forecast")

st.markdown(
    """
    <div class="wwu-callout wwu-decision">
      <strong>Management meaning:</strong> the question is no longer only
      “which bucket is largest?” It is “which user wants are rising, which
      loops keep users coming back, and which unresolved journeys need an owner?”
    </div>
    """,
    unsafe_allow_html=True,
)

with st.expander("How these timeline numbers are calculated", expanded=False):
    st.markdown(
        """
        **Short version:** this chart is not a keyword search. It counts
        support records that were mapped to an AI-discovered user want.

        **Pipeline used for this page:**

        1. Start from the support export and clean it into analysis-ready support records.
        2. Run the high-signal records through local Mistral/Ollama to extract the actual user want.
        3. Cluster those extracted wants into repeated user-want groups.
        4. Map every analysis-ready record to the nearest discovered want using multilingual embeddings.
        5. Count `records` by `assigned_want_id` and calendar month.

        **Formula behind one point on the line:**

        ```text
        records = count(rows)
        where selected semantic want = selected line
        and month(date_raw) = selected month
        ```

        **Why this differs from filtering Excel for "restore":**

        A keyword filter only counts rows that literally contain that word.
        The model-based count also includes the same intent written as
        "unban", "blocked account", "cannot access", "whitelist", "recover",
        screenshots/IDs with little text, and other multilingual wording.
        The tradeoff is that projected rows have confidence bands and review
        flags, so uncertainty is visible instead of hidden.
        """
    )
    method_cols = st.columns(4)
    method_cols[0].metric("Rows counted by page", f"{records:,}")
    method_cols[1].metric("Complete months used", f"{len(complete_months)}")
    method_cols[2].metric(
        "Mapped assignment rows",
        f"{len(assignment_audit):,}" if len(assignment_audit) else "-",
    )
    method_cols[3].metric(
        "Source table",
        "user_wants_all_assignments.csv" if len(assignment_audit) else "missing",
    )

st.subheader("Macro timeline: what changed month by month")
st.caption(
    "Trend comparisons use complete months only. A partial final month is excluded from the default chart so it does not fake a decline."
)
combine_duplicate_titles = st.toggle(
    "Combine clusters with the same human title",
    value=True,
    help=(
        "Management view: combine subclusters that received the same human title. "
        "Turn off to audit each model cluster ID separately."
    ),
)
if combine_duplicate_titles:
    monthly_chart = (
        monthly.groupby(["month", "month_date", "want_title"], as_index=False)
        .agg(
            records=("records", "sum"),
            unique_users=("unique_users", "sum"),
            failed_or_open_records=("failed_or_open_records", "sum"),
            review_queue_records=("review_queue_records", "sum"),
        )
        .rename(columns={"want_title": "display_want"})
    )
    monthly_chart["failed_or_open_share"] = (
        monthly_chart["failed_or_open_records"] / monthly_chart["records"].clip(lower=1)
    )
    monthly_chart["review_queue_share"] = (
        monthly_chart["review_queue_records"] / monthly_chart["records"].clip(lower=1)
    )
    audit_match_col = "want_title"
else:
    monthly_chart = monthly.copy()
    audit_match_col = "display_want"

include_partial = st.toggle("Include partial months", value=False)
trend_source = monthly_chart if include_partial else monthly_chart[monthly_chart["month"].astype(str).isin(complete_months)]
top_titles = (
    trend_source.groupby("display_want")["records"]
    .sum()
    .sort_values(ascending=False)
    .head(10)
    .index.tolist()
)
selected_titles = st.multiselect("Wants on timeline", top_titles, default=top_titles[:6])
trend_view = trend_source[trend_source["display_want"].isin(selected_titles)]
if len(trend_view):
    fig = px.line(
        trend_view.sort_values("month_date"),
        x="month_date",
        y="records",
        color="display_want",
        markers=True,
        labels={"month_date": "Month", "records": "Mapped support records", "display_want": "Want"},
        height=430,
    )
    fig.update_layout(margin=dict(l=10, r=10, t=18, b=10), legend=dict(orientation="h", y=-0.24))
    st.plotly_chart(fig, width="stretch")

if len(assignment_audit):
    with st.expander("Audit one timeline number", expanded=False):
        audit_options = selected_titles or top_titles
        audit_want = st.selectbox("Want line to audit", audit_options)
        month_options = (
            trend_source[trend_source["display_want"].eq(audit_want)]["month"]
            .dropna()
            .astype(str)
            .sort_values()
            .unique()
            .tolist()
        )
        if month_options:
            default_month_idx = len(month_options) - 1
            audit_month = st.selectbox("Month to audit", month_options, index=default_month_idx)
            audit_rows = assignment_audit[
                assignment_audit[audit_match_col].eq(audit_want)
                & assignment_audit["month"].astype(str).eq(str(audit_month))
            ].copy()
            all_time_rows = assignment_audit[assignment_audit[audit_match_col].eq(audit_want)].copy()
            chart_count = int(
                trend_source[
                    trend_source["display_want"].eq(audit_want)
                    & trend_source["month"].astype(str).eq(str(audit_month))
                ]["records"].sum()
            )

            a1, a2, a3 = st.columns(3)
            a1.metric("Chart count for this month", f"{chart_count:,}")
            a2.metric("Underlying rows found", f"{len(audit_rows):,}")
            a3.metric("All-time rows for this want", f"{len(all_time_rows):,}")
            st.caption(
                "If the first two numbers match, the point on the chart is reproducible from the underlying assignment table."
            )

            keyword = st.text_input(
                "Compare against a literal keyword filter",
                value="restore",
                help="This shows why a spreadsheet keyword search can be much smaller than the semantic want count.",
            )
            text_cols = [c for c in ["question_flat", "question"] if c in assignment_audit.columns]
            if keyword and text_cols:
                haystack = assignment_audit[text_cols].fillna("").astype(str).agg(" ".join, axis=1)
                keyword_mask = haystack.str.contains(keyword, case=False, regex=False, na=False)
                semantic_mask = assignment_audit[audit_match_col].eq(audit_want)
                month_mask = assignment_audit["month"].astype(str).eq(str(audit_month))
                k1, k2, k3, k4 = st.columns(4)
                k1.metric(f'Rows containing "{keyword}"', f"{int(keyword_mask.sum()):,}")
                k2.metric("Semantic want rows", f"{int(semantic_mask.sum()):,}")
                k3.metric(
                    f'"{keyword}" in selected month',
                    f"{int((keyword_mask & month_mask).sum()):,}",
                )
                k4.metric(
                    "Semantic rows in selected month",
                    f"{int((semantic_mask & month_mask).sum()):,}",
                )
                st.caption(
                    f'Keyword rows answer “where does the text contain `{keyword}`?”. '
                    "Semantic rows answer “where is the user trying to accomplish this want?”."
                )

            show_cols = [
                "source_row",
                "date_raw",
                "uid",
                "category",
                "status_en",
                "assigned_want_id",
                "want_title",
                "assignment_confidence",
                "confidence_band",
                "review_reason",
                "question_flat",
            ]
            show_cols = [c for c in show_cols if c in audit_rows.columns]
            display_audit = audit_rows[show_cols].copy()
            if "assignment_confidence" in display_audit.columns:
                display_audit["assignment_confidence"] = pd.to_numeric(
                    display_audit["assignment_confidence"],
                    errors="coerce",
                ).round(3)
            st.dataframe(
                display_audit.rename(
                    columns={
                        "source_row": "Ticket #",
                        "date_raw": "Date",
                        "uid": "UID",
                        "category": "Category",
                        "status_en": "Status",
                        "assigned_want_id": "Cluster ID",
                        "want_title": "Mapped want",
                        "assignment_confidence": "Mapping confidence",
                        "confidence_band": "Confidence band",
                        "review_reason": "Review reason",
                        "question_flat": "Ticket text",
                    }
                ),
                width="stretch",
                hide_index=True,
                height=360,
            )
            st.download_button(
                "Download audited rows",
                audit_rows.drop(
                    columns=[c for c in audit_rows.columns if c.lower().startswith("manager")],
                    errors="ignore",
                ).to_csv(index=False).encode("utf-8"),
                file_name=f"audit_{run_dir.name}_{audit_month}_{audit_want[:40].replace(' ', '_')}.csv",
                mime="text/csv",
                icon=":material/download:",
            )
        else:
            st.info("No monthly records are available for this selected want.")

trend_table = (
    emerging.sort_values(["momentum_score", "recent_records"], ascending=False)
    .head(8)
    .copy()
)
trend_table["Growth"] = trend_table["growth_ratio"].map(lambda v: f"{float(v) * 100:.1f}%")
trend_table["Recent failed/open"] = trend_table["recent_failed_or_open_share"].map(_pct)
trend_table["Review queue"] = trend_table["recent_review_queue_share"].map(_pct)
trend_table["Next month forecast"] = trend_table["forecast_next_month"].round(1)
trend_table["Recent records"] = trend_table["recent_records"].astype(int)
trend_table["Signal"] = trend_table["trend_label"].astype(str)
st.subheader("Early warning: what is likely to need attention next")
warn_chart, warn_table = st.columns([1.1, 1])
with warn_chart:
    fig = px.bar(
        trend_table.sort_values("momentum_score", ascending=True),
        x="momentum_score",
        y="display_want",
        color="recent_failed_or_open_share",
        orientation="h",
        labels={
            "momentum_score": "Momentum score",
            "display_want": "Want",
            "recent_failed_or_open_share": "Failed/open share",
        },
        color_continuous_scale="YlOrRd",
        height=430,
    )
    fig.update_layout(margin=dict(l=10, r=10, t=18, b=10))
    st.plotly_chart(fig, width="stretch")
with warn_table:
    st.dataframe(
        trend_table[
            [
                "display_want",
                "Signal",
                "Recent records",
                "Growth",
                "Next month forecast",
                "Recent failed/open",
                "Review queue",
            ]
        ].rename(columns={"display_want": "Want"}),
        width="stretch",
        hide_index=True,
        height=430,
    )

st.subheader("Micro reality: repeated-user journeys")
st.caption(
    "A row count cannot show this. These are UIDs that returned multiple times; the sequence shows whether support is solving a case or handling isolated fragments."
)

with st.sidebar:
    st.header("Journey filters")
    pattern_options = sorted(journeys["journey_pattern"].dropna().astype(str).unique().tolist())
    selected_patterns = st.multiselect("Journey archetype", pattern_options, default=pattern_options)
    min_records = st.slider("Minimum records per UID", 2, int(max(2, journeys["records"].max())), 3)
    unresolved_min = st.slider("Minimum failed/open share", 0.0, 1.0, 0.0, 0.05)

journey_view = journeys[
    journeys["journey_pattern"].astype(str).isin(selected_patterns)
    & (pd.to_numeric(journeys["records"], errors="coerce").fillna(0) >= min_records)
    & (pd.to_numeric(journeys["failed_or_open_share"], errors="coerce").fillna(0) >= unresolved_min)
].copy()
journey_view = journey_view.sort_values("severity_score", ascending=False)

j1, j2, j3, j4 = st.columns(4)
j1.metric("UIDs matching filters", f"{len(journey_view):,}")
j2.metric("Records in those journeys", f"{int(journey_view['records'].sum()):,}" if len(journey_view) else "0")
j3.metric("Median active days", f"{float(journey_view['active_days'].median()):.0f}" if len(journey_view) else "0")
j4.metric("Median wants per UID", f"{float(journey_view['unique_wants'].median()):.1f}" if len(journey_view) else "0")

show_journeys = journey_view.head(80).copy()
show_journeys["Failed/open"] = show_journeys["failed_or_open_share"].map(_pct)
st.dataframe(
    show_journeys[
        [
            "uid",
            "records",
            "active_days",
            "unique_wants",
            "journey_pattern",
            "Failed/open",
            "latest_status",
            "latest_want",
            "want_path",
            "recommended_action",
        ]
    ].rename(
        columns={
            "uid": "UID",
            "records": "Records",
            "active_days": "Active days",
            "unique_wants": "Unique wants",
            "journey_pattern": "Pattern",
            "latest_status": "Latest status",
            "latest_want": "Latest want",
            "want_path": "Journey path",
            "recommended_action": "Recommended action",
        }
    ),
    width="stretch",
    hide_index=True,
    height=340,
)

if len(journey_view):
    st.subheader("Roadmap of one user")
    uid_options = journey_view["uid"].astype(str).head(80).tolist()
    chosen_uid = st.selectbox("Choose a repeat user", uid_options)
    chosen = journey_view[journey_view["uid"].astype(str).eq(chosen_uid)].iloc[0]
    user_events = events[events["uid"].astype(str).eq(chosen_uid)].copy()
    user_events["date_dt"] = pd.to_datetime(user_events["date"], errors="coerce")
    user_events["event_label"] = user_events["event_index"].astype(str) + ". " + user_events["want_title"].astype(str)

    st.markdown(
        f"""
        <div class="wwu-callout">
          <strong>UID {chosen_uid}</strong>: {int(chosen['records'])} records over
          {int(chosen['active_days'])} days, {int(chosen['unique_wants'])} distinct wants.
          Pattern: <strong>{_clean(chosen.get('journey_pattern'))}</strong><br>
          <strong>Recommended action:</strong> {_clean(chosen.get('recommended_action'))}
        </div>
        """,
        unsafe_allow_html=True,
    )
    if len(user_events):
        fig = go.Figure()
        for _, row in user_events.iterrows():
            fig.add_trace(
                go.Scatter(
                    x=[row.get("date_dt")],
                    y=[row.get("event_index")],
                    mode="markers+text",
                    marker=dict(size=13, color=_status_color(row.get("status")), line=dict(width=1, color="#ffffff")),
                    text=[str(row.get("event_index"))],
                    textposition="middle center",
                    hovertemplate=(
                        "<b>%{customdata[0]}</b><br>Date: %{x|%Y-%m-%d}<br>Status: %{customdata[1]}<br>"
                        "Question: %{customdata[2]}<extra></extra>"
                    ),
                    customdata=[
                        [
                            _clean(row.get("want_title")),
                            _clean(row.get("status")),
                            _clean(row.get("question")),
                        ]
                    ],
                    showlegend=False,
                )
            )
        fig.update_layout(
            height=330,
            margin=dict(l=10, r=10, t=18, b=10),
            xaxis_title="Date",
            yaxis_title="Event number",
        )
        st.plotly_chart(fig, width="stretch")

        display_events = user_events[
            [
                "event_index",
                "date",
                "want_title",
                "category",
                "status",
                "actual_user_want",
                "support_next_step",
                "product_opportunity",
                "question",
            ]
        ].rename(
            columns={
                "event_index": "#",
                "date": "Date",
                "want_title": "Want",
                "category": "Source category",
                "status": "Status",
                "actual_user_want": "AI-read actual want",
                "support_next_step": "Suggested next step",
                "product_opportunity": "Product/process opportunity",
                "question": "Ticket text",
            }
        )
        st.dataframe(display_events, width="stretch", hide_index=True, height=420)

st.subheader("Journey archetypes: where operations needs playbooks")
archetype_show = archetypes.copy()
archetype_show["Failed/open"] = archetype_show["failed_or_open_share"].map(_pct)
archetype_show["Avg unique wants"] = archetype_show["avg_unique_wants"].round(1)
st.dataframe(
    archetype_show[
        [
            "journey_pattern",
            "users",
            "records",
            "median_records_per_user",
            "median_active_days",
            "Avg unique wants",
            "Failed/open",
            "top_wants",
            "recommended_action",
        ]
    ].rename(
        columns={
            "journey_pattern": "Pattern",
            "users": "Users",
            "records": "Records",
            "median_records_per_user": "Median records/user",
            "median_active_days": "Median active days",
            "top_wants": "Top wants inside this pattern",
            "recommended_action": "Recommended operating move",
        }
    ),
    width="stretch",
    hide_index=True,
    height=340,
)

st.download_button(
    "Download longitudinal findings",
    data=(run_dir / "longitudinal_findings.md").read_bytes(),
    file_name=f"longitudinal_findings_{run_dir.name}.md",
    mime="text/markdown",
    icon=":material/download:",
)
