"""Browse any data table in this run.

Auto-discovers every CSV in the run folder. For any chosen file: shows column
types, lets you filter/sort/search, and offers automatic charts for numeric and
categorical columns. Works for any new output without code changes.

Teaching
--------
This page is a *generic CSV browser* — it knows nothing about the
6,728-ticket pipeline specifically. Every helper function inspects a
DataFrame and decides what to show. New CSVs appear in the dropdown the
moment they land in the run folder; no code changes needed.

* **Auto-discovery.** ``list_csvs(str(run_dir))`` from ``lib`` walks the
  run directory and returns every ``*.csv`` it finds. The dropdown label
  for each file includes its size and last-modified time so the user
  knows which tables were just refreshed.

* **Schema panel.** A single ``pd.DataFrame`` is built from four pandas
  introspection methods: ``df.dtypes`` (per-column dtype),
  ``df.isna().sum()`` (count of empty cells), ``df.isna().mean() * 100``
  (percent empty), and ``df[c].nunique()`` (distinct values per column).
  These four numbers tell you almost everything you need to know about a
  new dataset; they are the standard "first look" toolkit.

* **``df.memory_usage(deep=True).sum()``.** Returns the DataFrame's
  total bytes, including the actual string contents (not just pointer
  sizes). ``deep=True`` is the difference between "this DataFrame is
  ~kilobytes" and the truth ("this DataFrame holds 200MB of strings").
  Call it whenever you have a frame you suspect is huge.

* **Auto-detect numeric vs categorical columns.**
  ``df.select_dtypes(include="number")`` returns the numeric columns by
  pandas dtype. The categorical detector is a list comprehension
  ``[c for c in df.columns if df[c].dtype == "object" and 1 <
  df[c].nunique() <= 80]`` — must be string-typed, must have between 2
  and 80 distinct values (free-text columns blow past 80; constant
  columns have 1). Tweak those bounds as you learn what shape your data
  takes.

* **``st.tabs([...])`` to offer multiple chart types.** ``st.tabs`` lets
  the page show a histogram tab, a counts tab, a scatter tab, and a
  boxplot tab without scrolling. The list ``tabs_to_show`` is built
  conditionally — we only show "Number vs number" if the table has at
  least two numeric columns. Empty tabs are confusing; conditional tabs
  are clean.

* **``df.sample(sample_n, random_state=42)``.** For the scatter tab on
  large tables we sample down to 5,000 rows. ``random_state=42`` pins the
  RNG seed so the same sample appears across reruns — reproducibility is
  a virtue even on exploratory plots.

* **``px.scatter(..., render_mode="webgl")``.** Same trick as the ticket
  map: WebGL rendering keeps the scatter responsive on tens of thousands
  of points. Pair it with ``opacity=0.6`` so dense regions get visibly
  darker.

* **Sort widget.** ``st.checkbox("Descending", value=True)`` paired with
  ``ascending=not sort_desc`` is the cleanest way to expose a sort-order
  toggle. The default is descending because users almost always want
  "biggest first".

* **Text search across one column.**
  ``f[text_col].astype(str).str.contains(text_query, case=False,
  na=False)`` is pandas' equivalent of SQL's case-insensitive ``LIKE``.
  ``na=False`` says "treat null cells as not-matching"; without it,
  pandas raises on null values.

* **Download button.** Same as the Find-a-Ticket page:
  ``f.to_csv(index=False).encode("utf-8")`` produces the bytes the
  download needs. Notice we download the *filtered* view, not the whole
  DataFrame — users almost always want what they're looking at.

* **Why a generic browser?** Because new analysis stages add new CSVs.
  Without this page you'd have to write a new dashboard tab for every
  file. With it, the analyst can poke at any new artefact within
  seconds of it landing on disk.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
from lib import (
    chart_picker,
    counts_df,
    file_mtime,
    file_size_bytes,
    human_size,
    list_csvs,
    load_csv,
    run_picker,
)

st.title("Browse data tables")
st.caption(
    "Every CSV file produced by the analysis is here. Pick a file to see its "
    "columns, filter and sort the rows, and get automatic charts."
)

run_dir = run_picker()
if run_dir is None:
    st.stop()

csvs = list_csvs(str(run_dir))
if not csvs:
    st.warning("No CSV files in this run.")
    st.stop()

st.caption(f"{len(csvs)} data tables available in this run.")
labeled = []
for name in csvs:
    path = run_dir / name
    labeled.append(
        f"{name}   ·   {human_size(file_size_bytes(path))}   ·   "
        f"{file_mtime(path).strftime('%m-%d %H:%M') if file_mtime(path) else ''}"
    )

choice_label = st.selectbox("Data table", labeled)
choice = csvs[labeled.index(choice_label)]
df = load_csv(str(run_dir), choice)

if df is None or df.empty:
    st.warning("This file is empty.")
    st.stop()

# ---- Schema panel -------------------------------------------------------

st.subheader(f"`{choice}`")
sc1, sc2, sc3 = st.columns(3)
sc1.metric("Rows", f"{len(df):,}")
sc2.metric("Columns", len(df.columns))
sc3.metric("In-memory size", human_size(int(df.memory_usage(deep=True).sum())))

with st.expander("Column types and stats", expanded=False):
    info = pd.DataFrame(
        {
            "Column": df.columns,
            "Type": df.dtypes.astype(str).values,
            "Empty cells": df.isna().sum().values,
            "Empty %": (df.isna().mean() * 100).round(1).astype(str) + "%",
            "Distinct values": [df[c].nunique() for c in df.columns],
        }
    )
    st.dataframe(info, use_container_width=True, hide_index=True)

# ---- Filtering ----------------------------------------------------------

with st.sidebar:
    st.header("Filters for this table")
    text_col = st.selectbox(
        "Text-search column",
        ["(none)"] + df.select_dtypes(include="object").columns.tolist(),
    )
    text_query = st.text_input("Contains", placeholder="search text...") if text_col != "(none)" else ""
    sort_col = st.selectbox("Sort by", ["(default)"] + df.columns.tolist())
    sort_desc = st.checkbox("Descending", value=True)
    n_rows = len(df)
    if n_rows <= 50:
        # Slider needs min < max. For tiny tables, just show every row.
        st.caption(f"Table is small ({n_rows} rows) — showing all of them.")
        max_rows = n_rows
    else:
        slider_max = min(20000, n_rows)
        slider_default = min(2000, slider_max)
        max_rows = st.slider(
            "Max rows to show",
            min_value=50,
            max_value=slider_max,
            value=slider_default,
            step=50,
        )

f = df.copy()
if text_col != "(none)" and text_query:
    f = f[f[text_col].astype(str).str.contains(text_query, case=False, na=False)]
if sort_col != "(default)":
    f = f.sort_values(sort_col, ascending=not sort_desc)
f = f.head(max_rows)

st.caption(f"Showing {len(f):,} of {len(df):,} rows")
st.dataframe(f, use_container_width=True, hide_index=True, height=480)

# ---- Auto-charts --------------------------------------------------------

st.subheader("Automatic charts")

numeric_cols = df.select_dtypes(include="number").columns.tolist()
categorical_cols = [
    c
    for c in df.columns
    if df[c].dtype == "object" and 1 < df[c].nunique() <= 80
]

tabs_to_show = []
if numeric_cols:
    tabs_to_show.append("Distribution of one number")
if categorical_cols:
    tabs_to_show.append("Counts of one category")
if numeric_cols and len(numeric_cols) >= 2:
    tabs_to_show.append("Number vs number")
if numeric_cols and categorical_cols:
    tabs_to_show.append("Number across categories")

if tabs_to_show:
    sections = st.tabs(tabs_to_show)
    idx = 0

    if "Distribution of one number" in tabs_to_show:
        with sections[idx]:
            col = st.selectbox("Column", numeric_cols, key="num_dist")
            fig = px.histogram(df, x=col, nbins=40, height=320)
            fig.update_layout(margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig, use_container_width=True)
            st.write(df[col].describe().to_frame().T)
        idx += 1

    if "Counts of one category" in tabs_to_show:
        with sections[idx]:
            col = st.selectbox("Column", categorical_cols, key="cat_dist")
            top_n = st.slider("Top N", 5, 50, 15, key="cat_topn")
            counts = df[col].value_counts().head(top_n)
            chart_picker(
                counts_df(counts, col, "count"),
                label_col=col,
                value_col="count",
                key_prefix="csv_browser_cat",
                default="Horizontal bars",
            )
        idx += 1

    if "Number vs number" in tabs_to_show:
        with sections[idx]:
            x_col = st.selectbox("X axis", numeric_cols, key="xy_x")
            y_col = st.selectbox("Y axis", [c for c in numeric_cols if c != x_col], key="xy_y")
            color_col = st.selectbox("Color (optional)", ["(none)"] + categorical_cols + numeric_cols, key="xy_c")
            sample_n = min(5000, len(df))
            sub = df.sample(sample_n, random_state=42) if len(df) > sample_n else df
            fig = px.scatter(
                sub,
                x=x_col,
                y=y_col,
                color=None if color_col == "(none)" else color_col,
                opacity=0.6,
                height=480,
                render_mode="webgl",
            )
            fig.update_layout(margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig, use_container_width=True)
        idx += 1

    if "Number across categories" in tabs_to_show:
        with sections[idx]:
            cat = st.selectbox("Category", categorical_cols, key="ncat_cat")
            num = st.selectbox("Number", numeric_cols, key="ncat_num")
            fig = px.box(df, x=cat, y=num, points="outliers", height=480)
            fig.update_layout(margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig, use_container_width=True)

st.download_button(
    "Download filtered view as CSV",
    f.to_csv(index=False).encode("utf-8"),
    file_name=f"filtered_{choice}",
    mime="text/csv",
)
