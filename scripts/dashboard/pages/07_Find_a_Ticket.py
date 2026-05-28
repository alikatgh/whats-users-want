"""Find a ticket — search and filter the full ticket dataset.

Teaching
--------
This page is a *DuckDB-backed search engine* over the 6,728 enriched
tickets. The user picks filters in the sidebar; we translate them into a
parameterised SQL query and let DuckDB return a DataFrame. The structure
is a great worked example of mixing Streamlit, DuckDB, and pandas.

* **``@st.cache_resource`` vs ``@st.cache_data``.** The two flavours of
  Streamlit's cache decorator look interchangeable but solve different
  problems. ``cache_resource`` is for things that must *not* be copied
  between reruns: open database connections, file handles, model
  instances. ``cache_data`` is for *immutable values*: DataFrames, lists,
  dicts. We mark ``get_con`` with ``cache_resource`` (the connection is a
  long-lived handle) and ``distinct`` with ``cache_data`` (the result is
  a list of strings).

* **Fallback to in-memory DuckDB.** ``get_con`` first tries
  ``analysis.duckdb`` (a pre-built database file). If that's missing it
  spins up an in-memory DuckDB and creates a *view* over the CSV via
  ``CREATE VIEW enriched_tickets AS SELECT * FROM read_csv_auto(...)``.
  This means the page works even on partial runs that haven't built the
  full database yet.

* **Parameterised SQL via ``?`` placeholders.** ``con.execute(sql, [v1,
  v2])`` substitutes parameters server-side. Never f-string user input
  into SQL — even on a local read-only database, the habit prevents
  injection bugs the day you point this at a real warehouse. The
  ``in_clause`` helper builds ``"col IN (?, ?, ?)"`` and ``extends`` the
  params list, which is the standard SQL-injection-safe way to do an
  ``IN`` clause with a variable-length value list.

* **``humanize_desire`` for the desire filter.** The sidebar shows
  "Recover account access" but the SQL receives ``"recover_access"``. We
  build a label-to-code dict (``desire_label_map``) so the multiselect
  shows pretty labels and we resolve back to codes before querying.

* **Case-insensitive text search.** ``LOWER("question") LIKE ?`` paired
  with ``f"%{text_query.lower()}%"`` lets a user type in any case and
  match anywhere in the ticket text. Wrap the search term with ``%`` on
  both sides for substring matching; one ``%`` would force a prefix or
  suffix match.

* **Two-query pattern.** The page issues two queries: a ``COUNT(*)`` for
  the "how many tickets matched" KPI, and a ``SELECT ... LIMIT N`` for
  the displayed table. This is faster than fetching everything and
  counting in pandas, and lets us tell the user "we matched 3,217
  tickets but are only displaying 500".

* **``ORDER BY context_depth_score DESC``.** When the user has a broad
  filter, we sort by how thoroughly each ticket was documented so they
  see the meatiest examples first. Always sort by something useful when
  you ``LIMIT``.

* **``con.execute(sql).df()``.** DuckDB's ``.df()`` returns a pandas
  DataFrame directly — no manual cursor unpacking. After the query we
  ``.map(humanize_desire)`` over the ``primary_desire`` column so the
  table shows friendly labels.

* **``st.expander`` for the detail view.** The single-ticket drill-down
  lives inside an ``st.expander``: the section is collapsed by default,
  keeping the page tidy, and clicking opens it. Pair an expander with a
  ``selectbox`` for an "open one row to inspect it" workflow.

* **``st.download_button``.** Streamlit's built-in CSV exporter. Pass it
  bytes (``df.to_csv(index=False).encode("utf-8")``), a filename, and a
  MIME type and the user gets a download link. ``index=False`` keeps the
  meaningless integer index out of the export.
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pandas as pd
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
from lib import chart_picker, counts_df, humanize_desire, run_picker

st.title("Find a ticket")
st.caption(
    "Search every ticket in this run by primary desire, category, status, "
    "or any text. Click any row in the table to expand details below."
)

run_dir = run_picker()
if run_dir is None:
    st.stop()

csv_path = run_dir / "enriched_tickets.csv"
if not csv_path.exists():
    st.warning("`enriched_tickets.csv` is missing in this run.")
    st.stop()


@st.cache_resource(show_spinner=False)
def get_con(run_dir_str: str) -> duckdb.DuckDBPyConnection:
    """Open (or build) a DuckDB connection for the given run directory.

    Prefers a pre-built ``analysis.duckdb`` in the run folder. When that file
    is missing, falls back to an in-memory database with an
    ``enriched_tickets`` view over the run's CSV. The connection is cached
    via ``@st.cache_resource`` so every Streamlit rerun reuses the same
    handle instead of reopening the file.

    Args:
        run_dir_str: Path to the run directory as a string. Passed as a
            string (not a ``Path``) because Streamlit's cache key is built
            from the arguments and strings hash cleanly.

    Returns:
        A read-only DuckDB connection that exposes an ``enriched_tickets``
        table or view.
    """
    db_path = Path(run_dir_str) / "analysis.duckdb"
    if db_path.exists():
        return duckdb.connect(str(db_path), read_only=True)
    con = duckdb.connect()
    con.execute(
        f"CREATE VIEW enriched_tickets AS SELECT * FROM read_csv_auto('{Path(run_dir_str) / 'enriched_tickets.csv'}', HEADER=True)"
    )
    return con


con = get_con(str(run_dir))


@st.cache_data(show_spinner=False)
def distinct(col: str) -> list[str]:
    """Return the sorted list of distinct non-null values in a column.

    Used to populate sidebar multiselect filters (managers, categories,
    statuses, …). Wrapped with ``@st.cache_data`` so the query runs once
    per column per session and subsequent reruns hit the in-memory cache.

    Args:
        col: Name of the column on the ``enriched_tickets`` table. The
            column name is interpolated into SQL after being wrapped in
            double quotes, so it must be trusted (i.e. hard-coded in this
            file, not user-supplied).

    Returns:
        A list of stringified distinct values, sorted ascending. Returns
        an empty list if the column does not exist or the query errors.
    """
    try:
        rows = con.execute(f'SELECT DISTINCT "{col}" FROM enriched_tickets WHERE "{col}" IS NOT NULL ORDER BY 1').fetchall()
        return [str(r[0]) for r in rows if r[0] is not None]
    except Exception:
        return []


# ---- Sidebar filters ----------------------------------------------------

with st.sidebar:
    st.header("Filters")
    desire_codes = distinct("primary_desire")
    desire_label_map = {humanize_desire(d): d for d in desire_codes}
    sel_desire_labels = st.multiselect("Primary desire", list(desire_label_map.keys()))
    sel_desire = [desire_label_map[label] for label in sel_desire_labels]
    sel_category = st.multiselect("Category", distinct("category"))
    sel_status = st.multiselect("Status", distinct("status_en"))
    sel_band = st.multiselect("Note evidence level", ["thin", "basic", "rich", "forensic"])
    text_query = st.text_input("Text contains", placeholder="dealer, scam, channel, разблокир...")
    limit = st.slider("Max rows to show", 50, 5000, 500, step=50)

clauses: list[str] = []
params: list = []


def in_clause(col: str, values: list[str]) -> None:
    """Append a parameterised ``col IN (?, ?, ...)`` clause to the WHERE list.

    Mutates the module-level ``clauses`` and ``params`` lists in place so
    the caller can simply call ``in_clause("manager", sel_manager)`` for
    each filter without juggling local variables. The placeholders count
    matches the number of values, and the values are appended to ``params``
    in order — this is the standard SQL-injection-safe approach to building
    a variable-length ``IN`` clause.

    Args:
        col: Trusted column name to filter on (interpolated into SQL after
            being wrapped in double quotes).
        values: Selected values from the sidebar widget. When empty, the
            function returns without modifying state — that is, *no
            filter applied* is the correct behaviour for an empty
            multiselect.

    Returns:
        ``None``. The function exists for its side effects on ``clauses``
        and ``params``.
    """
    if not values:
        return
    placeholders = ",".join(["?"] * len(values))
    clauses.append(f'"{col}" IN ({placeholders})')
    params.extend(values)


in_clause("primary_desire", sel_desire)
in_clause("category", sel_category)
in_clause("status_en", sel_status)
in_clause("context_depth_band", sel_band)
if text_query:
    clauses.append('LOWER("question") LIKE ?')
    params.append(f"%{text_query.lower()}%")

where_sql = " AND ".join(clauses) if clauses else "1=1"

cols_to_show = [
    "source_row",
    "date_raw",
    "uid",
    "category",
    "question_kind",
    "status_en",
    "primary_desire",
    "context_depth_score",
    "context_depth_band",
    "char_count",
    "url_count",
    "image_url_count",
    "is_resolved",
    "question_flat",
]
cols_sql = ", ".join(f'"{c}"' for c in cols_to_show)

count_sql = f"SELECT COUNT(*) FROM enriched_tickets WHERE {where_sql}"
data_sql = f"SELECT {cols_sql} FROM enriched_tickets WHERE {where_sql} ORDER BY context_depth_score DESC LIMIT {limit}"

n_total = con.execute(count_sql, params).fetchone()[0]
df = con.execute(data_sql, params).df()
if "primary_desire" in df.columns:
    df["primary_desire"] = df["primary_desire"].map(humanize_desire)

c1, c2, c3 = st.columns(3)
c1.metric("Tickets matching filters", f"{n_total:,}")
c2.metric("Showing in table", f"{len(df):,}")
c3.metric(
    "Avg note evidence score",
    f"{df['context_depth_score'].mean():.2f}" if "context_depth_score" in df.columns and len(df) else "—",
)

# ---- Quick distribution of the filtered set ----------------------------

if len(df):
    with st.expander("Distribution of these results", expanded=False):
        breakdown_options = {}
        for col, label in [
            ("primary_desire", "Primary desire"),
            ("category", "Category"),
            ("status_en", "Status"),
            ("context_depth_band", "Evidence level"),
        ]:
            if col in df.columns and df[col].dropna().nunique() > 1:
                breakdown_options[label] = col
        if breakdown_options:
            chosen_label = st.selectbox("Break results down by", list(breakdown_options.keys()))
            chosen_col = breakdown_options[chosen_label]
            counts = df[chosen_col].fillna("(missing)").value_counts().head(30)
            chart_picker(
                counts_df(counts, chosen_label, "Tickets"),
                label_col=chosen_label,
                value_col="Tickets",
                key_prefix="findaticket_dist",
                default="Horizontal bars",
            )
        else:
            st.write("Not enough variety in the filtered results to break down.")

rename_map = {
    "source_row": "Ticket #",
    "date_raw": "Date",
    "uid": "User ID",
    "category": "Category",
    "question_kind": "Question kind",
    "status_en": "Status",
    "primary_desire": "Primary desire",
    "context_depth_score": "Note evidence score",
    "context_depth_band": "Evidence level",
    "char_count": "Length (chars)",
    "url_count": "Links",
    "image_url_count": "Screenshots",
    "is_resolved": "Resolved",
    "question_flat": "Ticket text (preview)",
}
st.dataframe(df.rename(columns=rename_map), width="stretch", hide_index=True, height=520)

# ---- Single-ticket view -------------------------------------------------

with st.expander("Open one ticket in detail"):
    if len(df):
        chosen = st.selectbox("Pick a ticket", df["source_row"].astype(str).tolist())
        full_sql = 'SELECT * FROM enriched_tickets WHERE "source_row" = ?'
        row = con.execute(full_sql, [chosen]).df()
        if len(row):
            r = row.iloc[0]
            st.write(
                f"**Category:** {r.get('category', '')}  ·  "
                f"**Status:** {r.get('status_en', '')}  ·  **Date:** {r.get('date_raw', '')}"
            )
            st.write(
                f"**Primary desire:** {r.get('primary_desire', '')}  ·  "
                f"**Evidence level:** {r.get('context_depth_band', '')}  ·  "
                f"**Score:** {r.get('context_depth_score', '')}"
            )
            st.markdown("**Original ticket text:**")
            st.code(str(r.get("question", "")), language="text")

st.download_button(
    "Download these rows as CSV",
    df.to_csv(index=False).encode("utf-8"),
    file_name="filtered_tickets.csv",
    mime="text/csv",
)
