"""No-ban evidence page.

Shows every support record where the moderation-team "no ban" keyword appears
in the manager-written ticket text. The matcher is normalized by default, so it
finds "no ban", "no-ban", "no_ban", and "noban".
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
from lib import chart_picker, counts_df, maybe_load_csv, run_picker


DEFAULT_PATTERN = r"\bno[\s_-]*ban\b"
SEARCH_COLUMNS = ["question", "question_flat", "model_text"]


def _clean(value: object) -> str:
    text = str(value or "").strip()
    if text.lower() in {"nan", "none", "null"}:
        return ""
    return text


def _source_key(series: pd.Series) -> pd.Series:
    return series.astype(str).str.replace(r"\.0$", "", regex=True)


def _snippet(text: object, pattern: re.Pattern[str], radius: int = 120) -> str:
    raw = _clean(text).replace("\n", " ")
    match = pattern.search(raw)
    if not match:
        return raw[: radius * 2].strip()
    start = max(0, match.start() - radius)
    end = min(len(raw), match.end() + radius)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(raw) else ""
    return f"{prefix}{raw[start:end].strip()}{suffix}"


def _matched_fields(row: pd.Series, pattern: re.Pattern[str]) -> list[str]:
    fields = []
    for col in SEARCH_COLUMNS:
        if col in row.index and pattern.search(_clean(row[col])):
            fields.append(col)
    return fields


def _build_no_ban_table(
    enriched: pd.DataFrame,
    assignments: pd.DataFrame | None,
    pattern_text: str,
) -> pd.DataFrame:
    pattern = re.compile(pattern_text, flags=re.IGNORECASE)
    work = enriched.copy()
    work["source_row"] = _source_key(work["source_row"])

    search_cols = [c for c in SEARCH_COLUMNS if c in work.columns]
    if not search_cols:
        return pd.DataFrame()
    haystack = work[search_cols].fillna("").astype(str).agg("\n".join, axis=1)
    matches = work[haystack.map(lambda text: bool(pattern.search(text)))].copy()
    if matches.empty:
        return matches

    matches["matched_fields"] = matches.apply(lambda row: ", ".join(_matched_fields(row, pattern)), axis=1)
    snippet_col = "question_flat" if "question_flat" in matches.columns else search_cols[0]
    matches["no_ban_snippet"] = matches[snippet_col].map(lambda text: _snippet(text, pattern))

    if assignments is not None and not assignments.empty and "source_row" in assignments.columns:
        assign = assignments.copy()
        assign["source_row"] = _source_key(assign["source_row"])
        attach_cols = [
            "source_row",
            "assigned_want_id",
            "want_title",
            "want_label",
            "assignment_confidence",
            "confidence_band",
            "needs_llm_review",
            "review_reason",
        ]
        attach_cols = [c for c in attach_cols if c in assign.columns]
        matches = matches.merge(assign[attach_cols].drop_duplicates("source_row"), on="source_row", how="left")

    if "date" in matches.columns:
        matches["date_sort"] = pd.to_datetime(matches["date"], errors="coerce")
    elif "date_raw" in matches.columns:
        matches["date_sort"] = pd.to_datetime(matches["date_raw"], errors="coerce", dayfirst=True)
    else:
        matches["date_sort"] = pd.NaT
    return matches.sort_values(["date_sort", "source_row"], ascending=[False, True]).drop(columns=["date_sort"])


st.title("No-ban mentions")
st.markdown(
    """
    <div class="wwu-eyebrow">Moderation keyword evidence</div>
    <div class="wwu-lede">
    This page extracts every support record where a no-ban keyword appears in
    the manager-written ticket content, then attaches the user-want mapping so
    the manager can see what those cases were actually about.
    </div>
    """,
    unsafe_allow_html=True,
)

run_dir = run_picker("Choose a run")
if run_dir is None:
    st.stop()

enriched = maybe_load_csv(run_dir, "enriched_tickets.csv")
assignments = maybe_load_csv(run_dir, "user_wants_all_assignments.csv")

if enriched is None or enriched.empty:
    st.warning("This run does not have `enriched_tickets.csv`.")
    st.stop()

with st.sidebar:
    st.header("No-ban search")
    pattern_text = st.text_input(
        "Regex pattern",
        DEFAULT_PATTERN,
        help="Default finds no ban, no-ban, no_ban, and noban.",
    )
    exact_hyphen_only = st.checkbox("Exact `no-ban` only", value=False)
    if exact_hyphen_only:
        pattern_text = r"\bno\-ban\b"
    show_full_text = st.checkbox("Show full ticket text column", value=False)

try:
    matches = _build_no_ban_table(enriched, assignments, pattern_text)
except re.error as exc:
    st.error(f"Invalid regex pattern: {exc}")
    st.stop()

exact_pattern = re.compile(r"\bno\-ban\b", flags=re.IGNORECASE)
normalized_pattern = re.compile(DEFAULT_PATTERN, flags=re.IGNORECASE)
search_cols = [c for c in SEARCH_COLUMNS if c in enriched.columns]
exact_count = 0
normalized_count = 0
if search_cols:
    all_text = enriched[search_cols].fillna("").astype(str).agg("\n".join, axis=1)
    exact_count = int(all_text.map(lambda text: bool(exact_pattern.search(text))).sum())
    normalized_count = int(all_text.map(lambda text: bool(normalized_pattern.search(text))).sum())

k1, k2, k3, k4 = st.columns(4)
k1.metric("Rows matching current search", f"{len(matches):,}")
k2.metric("Normalized no-ban rows", f"{normalized_count:,}")
k3.metric("Exact `no-ban` rows", f"{exact_count:,}")
k4.metric("Unique users", f"{matches['uid'].dropna().astype(str).nunique():,}" if "uid" in matches.columns else "-")

st.info(
    "The current data uses **`No ban` / `no ban now`** with a space, not the hyphenated `no-ban` form. "
    "The default matcher therefore uses normalized matching so the moderation keyword evidence is not missed.",
    icon=":material/search_check:",
)

if matches.empty:
    st.warning("No rows matched this pattern in the selected run.")
    st.stop()

with st.sidebar:
    st.header("Filters")
    if "manager" in matches.columns:
        managers = sorted(matches["manager"].fillna("(missing)").astype(str).unique())
        selected_managers = st.multiselect("Manager", managers, default=managers)
        matches = matches[matches["manager"].fillna("(missing)").astype(str).isin(selected_managers)]
    if "category" in matches.columns:
        categories = sorted(matches["category"].fillna("(missing)").astype(str).unique())
        selected_categories = st.multiselect("Category", categories, default=categories)
        matches = matches[matches["category"].fillna("(missing)").astype(str).isin(selected_categories)]
    if "status_en" in matches.columns:
        statuses = sorted(matches["status_en"].fillna("(missing)").astype(str).unique())
        selected_statuses = st.multiselect("Status", statuses, default=statuses)
        matches = matches[matches["status_en"].fillna("(missing)").astype(str).isin(selected_statuses)]
    if "want_title" in matches.columns:
        wants = sorted(matches["want_title"].fillna("(missing)").astype(str).unique())
        selected_wants = st.multiselect("Mapped user want", wants, default=wants)
        matches = matches[matches["want_title"].fillna("(missing)").astype(str).isin(selected_wants)]

st.subheader("Where no-ban appears")
breakdown_cols = st.columns(3)
with breakdown_cols[0]:
    if "category" in matches.columns:
        st.markdown("**By source category**")
        chart_picker(
            counts_df(matches["category"].fillna("(missing)").value_counts(), "Category", "Rows"),
            "Category",
            "Rows",
            key_prefix="noban_category",
            default="Horizontal bars",
            options=("Horizontal bars", "Table"),
        )
with breakdown_cols[1]:
    if "status_en" in matches.columns:
        st.markdown("**By status**")
        chart_picker(
            counts_df(matches["status_en"].fillna("(missing)").value_counts(), "Status", "Rows"),
            "Status",
            "Rows",
            key_prefix="noban_status",
            default="Horizontal bars",
            options=("Horizontal bars", "Table"),
        )
with breakdown_cols[2]:
    if "want_title" in matches.columns:
        st.markdown("**By mapped user want**")
        chart_picker(
            counts_df(matches["want_title"].fillna("(missing)").value_counts(), "Want", "Rows"),
            "Want",
            "Rows",
            key_prefix="noban_want",
            default="Horizontal bars",
            options=("Horizontal bars", "Table"),
        )

st.subheader("No-ban evidence table")
show_cols = [
    "source_row",
    "date_raw",
    "manager",
    "uid",
    "category",
    "status_en",
    "want_title",
    "assignment_confidence",
    "confidence_band",
    "matched_fields",
    "no_ban_snippet",
]
if show_full_text:
    show_cols.append("question")
else:
    show_cols.append("question_flat")
show_cols = [c for c in show_cols if c in matches.columns]

rename = {
    "source_row": "Ticket #",
    "date_raw": "Date",
    "manager": "Manager",
    "uid": "UID",
    "category": "Category",
    "status_en": "Status",
    "want_title": "Mapped user want",
    "assignment_confidence": "Mapping confidence",
    "confidence_band": "Confidence band",
    "matched_fields": "Matched fields",
    "no_ban_snippet": "No-ban snippet",
    "question": "Full ticket text",
    "question_flat": "Ticket text",
}

display = matches[show_cols].copy()
if "assignment_confidence" in display.columns:
    display["assignment_confidence"] = pd.to_numeric(display["assignment_confidence"], errors="coerce").round(3)
st.dataframe(display.rename(columns=rename), width="stretch", hide_index=True, height=540)

with st.expander("Open one no-ban case in detail"):
    chosen = st.selectbox("Ticket #", matches["source_row"].astype(str).tolist())
    row = matches[matches["source_row"].astype(str).eq(chosen)].iloc[0]
    st.write(
        f"**Manager:** {_clean(row.get('manager'))}  ·  "
        f"**Category:** {_clean(row.get('category'))}  ·  "
        f"**Status:** {_clean(row.get('status_en'))}  ·  "
        f"**Date:** {_clean(row.get('date_raw'))}"
    )
    if "want_title" in row.index:
        st.write(
            f"**Mapped user want:** {_clean(row.get('want_title'))}  ·  "
            f"**Confidence:** {_clean(row.get('assignment_confidence'))} / {_clean(row.get('confidence_band'))}"
        )
    st.markdown("**No-ban snippet:**")
    st.code(_clean(row.get("no_ban_snippet")), language="text")
    st.markdown("**Full ticket text:**")
    st.code(_clean(row.get("question") or row.get("question_flat")), language="text")

download_cols = [
    c
    for c in [
        "source_row",
        "date_raw",
        "date",
        "manager",
        "uid",
        "category",
        "status_en",
        "want_title",
        "assignment_confidence",
        "confidence_band",
        "matched_fields",
        "no_ban_snippet",
        "question",
        "question_flat",
    ]
    if c in matches.columns
]
st.download_button(
    "Download no-ban cases as CSV",
    matches[download_cols].to_csv(index=False).encode("utf-8"),
    file_name=f"no_ban_mentions_{run_dir.name}.csv",
    mime="text/csv",
    icon=":material/download:",
)
