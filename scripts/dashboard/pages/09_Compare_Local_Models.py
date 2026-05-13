"""Compare local model outputs.

Auto-discovers every locally-produced extraction file in this run (rule-based
baseline, Gemma 270m / 1b / 4b, and hybrid) and lets you pick any two for
side-by-side comparison. Nothing is sent to any external service.

Teaching
--------
This page exists to *evaluate small local models against each other* on
the same 6,728 tickets without sending data anywhere. The structure is:
discover candidate files, pick two, count things in both, plot them
side-by-side, and offer a per-ticket diff at the bottom.

* **Filter out non-local files.** The discovery step skips anything
  starting with ``llm_extraction`` (those are status files) and anything
  with ``"openai"`` in the name. Everything left is a Gemma run, a
  rule-based baseline, or a hybrid — i.e. *something that ran on this
  machine*. Cloud comparisons live on a different page on purpose.

* **``format_func`` on a selectbox.** ``st.selectbox(... format_func=
  friendly_name)`` is a beautiful pattern: the dropdown displays
  ``friendly_name(option)`` (the pretty label) but the *return value* is
  the raw filename. So ``left`` ends up being
  ``"ollama_gemma3-4b_extractions.csv"``, not ``"Gemma 3 (4B)"``, and
  the loader can use it directly without reverse-mapping.

* **Side-by-side load.** ``left_df = load_csv(str(run_dir), left)`` and
  the same for ``right``. Both are pandas DataFrames; everything below
  this line operates on them.

* **Per-model summary.** ``summarize`` digs out row counts, valid-row
  counts, and the recorded ``_model``/``_backend`` strings. Returning a
  dict is a quick alternative to defining a dataclass for ad-hoc
  result aggregation.

* **Wide DataFrame from two value_counts.**
  ``pd.DataFrame({left: left_counts, right: right_counts}).fillna(0).astype(int)``
  is a useful idiom: each Series becomes a column, the union of their
  indexes becomes the row index, and missing categories on one side
  become 0. ``.astype(int)`` brings them back to integers after the
  ``fillna(0)`` (which would have made them floats).

* **Reset, melt, then bar chart.** Force-name the index first
  (``merged.index = merged.index.rename("Value")``), then
  ``reset_index().melt(id_vars="Value", var_name="Model",
  value_name="Tickets")`` turns a wide DataFrame (one column per
  model) into a long DataFrame (one row per category × model) so
  Plotly can draw a grouped bar chart with ``color="Model"``. Naming
  the index explicitly avoids the cross-pandas-version quirk where
  ``reset_index()`` names the new column "index" on some installs and
  the original column's name on others.

* **Set intersection for shared tickets.**
  ``set(left["source_row"].astype(str)) & set(right["source_row"].astype(str))``
  is Python's ``&`` operator on sets. It returns the IDs present in both
  files — only those tickets can be diffed. Casting to ``str`` first
  prevents 12 == "12" mismatches that you get when one file parsed the
  column as int and the other as object.

* **Per-ticket diff via list-of-dicts.** Building rows as
  ``{"Field": label, "Left": ..., "Right": ...}`` and feeding the list to
  ``pd.DataFrame`` is the most readable way to assemble a small comparison
  table. We trim to ``[:300]`` characters per cell so a runaway model
  output doesn't blow out the column width.

* **``[:300]`` cap on the diff selector.** ``sorted(common)[:300]`` keeps
  the dropdown to 300 ticket IDs even when thousands match — a multiselect
  with 6,000 entries is unusable. This is a UX constraint, not a
  correctness one.

* **Pre-canned comparison report.** If the run contains
  ``local_llm_model_comparison.md``, an expander surfaces it. Markdown
  files are rendered with ``st.markdown(...)``; reading them with
  ``read_text(encoding="utf-8")`` is robust against non-ASCII content
  (e.g. Russian ticket text).

* **Why bother comparing two models?** Because "the bigger model is
  better" is sometimes wrong. The 270M Gemma may flag the same tickets
  as the 4B, and if so you can run the cheap one in production and save
  GPU minutes. The diff view turns that hypothesis into a check you can
  do in 30 seconds.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
from lib import load_csv, run_picker

st.title("Compare local model outputs")
st.caption(
    "Pick any two locally-run extractions to compare. "
    "All models in this view are running on your own machine — no external services."
)

run_dir = run_picker()
if run_dir is None:
    st.stop()

extraction_files = sorted(
    [
        p.name
        for p in run_dir.glob("*extractions.csv")
        if not p.name.startswith("llm_extraction") and "openai" not in p.name.lower()
    ]
)
if not extraction_files:
    st.warning("No local extraction outputs in this run.")
    st.stop()

st.caption(f"{len(extraction_files)} local extraction files in this run.")


def friendly_name(filename: str) -> str:
    """Turn an extraction CSV filename into a human-readable model label.

    Strips the ``_extractions.csv`` suffix and applies a small set of
    rewriting rules so dropdowns and chart legends show readable names
    (``"Gemma 3 (4B)"``) instead of raw filenames
    (``"ollama_gemma3-4b_extractions.csv"``). Used as the ``format_func``
    on the model selectboxes — the rendered label is friendly but the
    selected value is the original filename, so downstream loaders need
    no reverse mapping.

    Args:
        filename: Basename of an extraction CSV in the run directory.

    Returns:
        A human-readable label. Falls back to the cleaned base name when
        no rule matches.
    """
    base = filename.replace("_extractions.csv", "").replace("_extractions", "")
    if base.startswith("ollama_hybrid_"):
        rest = base.replace("ollama_hybrid_", "")
        return f"Hybrid (rules + {rest})"
    if base.startswith("ollama_"):
        rest = base.replace("ollama_", "")
        return f"Local: {rest.replace('-', ' ')}"
    if base == "rules":
        return "Rule-based baseline (no model)"
    return base


# ---- Side-by-side -------------------------------------------------------

c_left, c_right = st.columns(2)
with c_left:
    left = st.selectbox(
        "Left model",
        extraction_files,
        index=0,
        format_func=friendly_name,
    )
with c_right:
    right_idx = 1 if len(extraction_files) > 1 else 0
    right = st.selectbox(
        "Right model",
        extraction_files,
        index=right_idx,
        format_func=friendly_name,
    )


def summarize(name: str) -> dict:
    """Load one extraction CSV and return a small dict of headline counts.

    Reads the file via ``load_csv`` and pulls out total rows, the number of
    rows in each ``_status`` bucket (``ok`` / ``bad_output`` / ``error``),
    and the recorded ``_model`` / ``_backend`` strings (when the columns
    exist). Used to populate the four KPI metrics at the top of the page
    and the per-model "Backend / Model" caption underneath.

    Args:
        name: Basename of an extraction CSV in the run directory.

    Returns:
        Dict with at least ``name`` and ``rows``. When the file is
        non-empty and contains the expected columns, also includes
        ``ok``, ``bad_output``, ``error``, ``model``, and ``backend``.
        Missing columns become ``None`` so the caller can still render
        without ``KeyError``.
    """
    df = load_csv(str(run_dir), name)
    if df is None or df.empty:
        return {"name": name, "rows": 0}
    summary = {
        "name": name,
        "rows": len(df),
        "ok": int((df.get("_status") == "ok").sum()) if "_status" in df.columns else None,
        "bad_output": int((df.get("_status") == "bad_output").sum()) if "_status" in df.columns else None,
        "error": int((df.get("_status") == "error").sum()) if "_status" in df.columns else None,
        "model": (df["_model"].iloc[0] if "_model" in df.columns and len(df) else None),
        "backend": (df["_backend"].iloc[0] if "_backend" in df.columns and len(df) else None),
    }
    return summary


left_df = load_csv(str(run_dir), left)
right_df = load_csv(str(run_dir), right)

l_sum = summarize(left)
r_sum = summarize(right)

m1, m2, m3, m4 = st.columns(4)
m1.metric(f"{friendly_name(left)} — tickets", f"{l_sum['rows']:,}")
m2.metric(f"{friendly_name(left)} — valid", f"{l_sum.get('ok') or 0:,}")
m3.metric(f"{friendly_name(right)} — tickets", f"{r_sum['rows']:,}")
m4.metric(f"{friendly_name(right)} — valid", f"{r_sum.get('ok') or 0:,}")

st.write(f"**Left model.** Backend: `{l_sum.get('backend')}`. Model: `{l_sum.get('model')}`.")
st.write(f"**Right model.** Backend: `{r_sum.get('backend')}`. Model: `{r_sum.get('model')}`.")

# ---- Job/emotion comparison --------------------------------------------

def value_counts(df: pd.DataFrame, col: str) -> pd.Series:
    """Return a value-counts Series for one column, safe on missing columns.

    Wraps ``df[col].fillna("(missing)").value_counts()`` with a presence
    check so the call returns an empty Series instead of raising when the
    column doesn't exist. Replacing nulls with the literal string
    ``"(missing)"`` makes them visible as a category in the resulting bar
    chart instead of silently disappearing.

    Args:
        df: DataFrame to inspect.
        col: Column name. May be absent from ``df.columns``.

    Returns:
        Series indexed by category with integer counts, sorted descending.
        Returns an empty ``Series(dtype="int64")`` when ``col`` is not in
        ``df``.
    """
    if col not in df.columns:
        return pd.Series(dtype="int64")
    return df[col].fillna("(missing)").value_counts()


comp_pairs = [
    ("job_to_be_done", "Jobs to be done"),
    ("user_emotion", "User emotions"),
    ("manager_note_quality", "Manager note quality"),
    ("_status", "Output status"),
    ("_quality_flag", "Quality flag"),
]

for col, label in comp_pairs:
    left_counts = value_counts(left_df, col) if left_df is not None else pd.Series()
    right_counts = value_counts(right_df, col) if right_df is not None else pd.Series()
    if not len(left_counts) and not len(right_counts):
        continue
    st.subheader(label)
    merged = pd.DataFrame(
        {
            friendly_name(left): left_counts,
            friendly_name(right): right_counts,
        }
    ).fillna(0).astype(int)
    if len(merged) > 25:
        merged = merged.sort_values(merged.columns[0], ascending=False).head(25)
    # Pandas versions disagree on what reset_index() names an unnamed index
    # column ("index" vs the original column's name vs nothing). Force a known
    # column name before melting.
    merged_long = merged.copy()
    merged_long.index = merged_long.index.rename("Value")
    melted = merged_long.reset_index().melt(
        id_vars="Value", var_name="Model", value_name="Tickets"
    )
    fig = px.bar(
        melted,
        x="Tickets",
        y="Value",
        color="Model",
        barmode="group",
        orientation="h",
        height=max(260, 24 * len(merged)),
    )
    fig.update_layout(
        margin=dict(l=10, r=10, t=10, b=10),
        yaxis={"categoryorder": "total ascending"},
        yaxis_title="",
        legend_title_text="",
    )
    st.plotly_chart(fig, width="stretch")

# ---- Risk level comparison ---------------------------------------------

risk_pairs = [
    ("urgency_level", "Urgency"),
    ("trust_risk_level", "Trust risk"),
    ("money_risk_level", "Money risk"),
    ("safety_policy_risk_level", "Safety / policy risk"),
]
risk_pairs = [
    (c, label)
    for c, label in risk_pairs
    if (left_df is not None and c in left_df.columns) or (right_df is not None and c in right_df.columns)
]
if risk_pairs:
    st.subheader("How the two models score risk")
    risk_tabs = st.tabs([label for _, label in risk_pairs])
    for (col, _label), tab in zip(risk_pairs, risk_tabs):
        with tab:
            rows = []
            if left_df is not None and col in left_df.columns:
                for v, n in left_df[col].fillna(0).astype(int).value_counts().items():
                    rows.append({"Risk level (1-5)": int(v), "Tickets": int(n), "Model": friendly_name(left)})
            if right_df is not None and col in right_df.columns:
                for v, n in right_df[col].fillna(0).astype(int).value_counts().items():
                    rows.append({"Risk level (1-5)": int(v), "Tickets": int(n), "Model": friendly_name(right)})
            if rows:
                fig = px.bar(
                    pd.DataFrame(rows),
                    x="Risk level (1-5)",
                    y="Tickets",
                    color="Model",
                    barmode="group",
                    height=320,
                )
                fig.update_layout(margin=dict(l=10, r=10, t=10, b=10))
                st.plotly_chart(fig, width="stretch")

# ---- Per-row diff for shared source_rows -------------------------------

if (
    left_df is not None
    and right_df is not None
    and "source_row" in left_df.columns
    and "source_row" in right_df.columns
):
    st.subheader("Compare one ticket across both models")
    common = set(left_df["source_row"].astype(str)) & set(right_df["source_row"].astype(str))
    st.caption(f"{len(common):,} tickets are present in both files.")
    if common:
        chosen = st.selectbox("Pick a ticket", sorted(common)[:300])
        l_row = left_df[left_df["source_row"].astype(str) == chosen].iloc[0]
        r_row = right_df[right_df["source_row"].astype(str) == chosen].iloc[0]
        compare_cols = [
            ("job_to_be_done", "Job to be done"),
            ("user_emotion", "Emotion"),
            ("urgency_level", "Urgency"),
            ("trust_risk_level", "Trust risk"),
            ("money_risk_level", "Money risk"),
            ("literal_request", "What user said"),
            ("actual_user_want", "What user actually wants"),
            ("support_next_step", "Suggested support step"),
            ("product_opportunity", "Product opportunity"),
            ("_status", "Output status"),
            ("_quality_flag", "Quality flag"),
            ("confidence", "Model confidence"),
        ]
        rows = []
        for c, label in compare_cols:
            if c in left_df.columns or c in right_df.columns:
                rows.append(
                    {
                        "Field": label,
                        f"{friendly_name(left)}": str(l_row.get(c, ""))[:300],
                        f"{friendly_name(right)}": str(r_row.get(c, ""))[:300],
                    }
                )
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

# ---- Pre-canned comparison report --------------------------------------

comparison_md = run_dir / "local_llm_model_comparison.md"
if comparison_md.exists():
    with st.expander("Notes on each local model (`local_llm_model_comparison.md`)"):
        st.markdown(comparison_md.read_text(encoding="utf-8"))
