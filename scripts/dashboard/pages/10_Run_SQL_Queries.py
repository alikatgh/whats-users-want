"""Run any SQL query against the run's local database.

Lists every table in `analysis.duckdb` and lets you query it directly. Useful
for power users; pre-built queries cover common questions for everyone else.

Teaching
--------
This page is a *SQL escape hatch* for the run's DuckDB database. Every
analysis output that landed as a CSV is also a table here. The page is
deliberately minimal: a table list, a schema browser, a dropdown of
canned queries, an editable textarea, and a result table. Together they
turn the dashboard into a tiny SQL IDE.

* **``duckdb.connect(path, read_only=True)``.** Opening the database
  read-only is a safety habit. The SQL console is meant for exploration;
  the read-only flag means a typo like ``DELETE FROM enriched_tickets``
  errors out instead of silently mutating the file. Always read-only when
  you don't intend to write.

* **``information_schema.tables``.** DuckDB exposes the standard SQL
  information schema, which means ``SELECT table_name, table_type FROM
  information_schema.tables`` works exactly the way it would in
  Postgres. This is the way to enumerate tables without coupling the
  dashboard to DuckDB-specific catalogue tables.

* **Schema browser.** ``SELECT column_name, data_type FROM
  information_schema.columns WHERE table_name = ? ORDER BY
  ordinal_position`` returns the column list for a specific table.
  ``ordinal_position`` is the column's index in the table's definition,
  so sorting by it gives you "natural" column order. The page also
  ``SELECT * FROM "table" LIMIT 10`` so the user sees a sample.

* **Pre-canned query dictionary pattern.** ``canned`` is a plain
  ``{name: sql}`` dict. The selectbox shows the names; picking one fills
  the textarea. This is the cleanest way to ship "common questions" to
  non-SQL-fluent users without locking them out of writing their own
  queries.

* **``st.text_area("SQL", value=initial_sql, height=180)``.** The text
  area is editable — picking a canned query is a *starting point*, not a
  read-only choice. Users can tweak the WHERE clause and re-run. This is
  the central ergonomic improvement over hard-coded reports.

* **``con.execute(sql).fetchdf()``.** Same as page 07: ``.fetchdf()``
  hands back a pandas DataFrame ready for ``st.dataframe``. No cursor
  unpacking, no row-by-row iteration.

* **``st.button("Run query")``.** A regular button; clicking sets ``run``
  to ``True`` for one rerun, then back to ``False``. The page actually
  executes the query whenever ``run or chosen_query != "(write my own)"``,
  which means picking a canned query auto-runs it the first time, and
  thereafter the user has to click the button to rerun. Subtle but
  intentional.

* **Error handling.** ``try / except Exception as exc`` plus
  ``st.error(f"Query failed: {exc}")`` catches malformed SQL and shows
  the DuckDB error string inline. Without the try/except, a typo in the
  textarea would crash the whole page.

* **Download button on the result.** ``df.to_csv(index=False).encode(
  "utf-8")`` for the bytes; the user gets a CSV download of whatever
  query they just ran. Pair this with the canned-query starter and you
  have a self-service exporter.

* **Why expose SQL at all?** Because some questions don't fit the other
  pages. "Show me every Russian-language ticket where the manager wrote
  fewer than 50 characters and the user mentioned a money amount" is a
  one-line query and a four-page navigation otherwise. The SQL console
  unblocks the analyst when the dashboard's pre-baked views fall short.
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pandas as pd
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
from lib import run_picker

st.title("Run SQL queries")
st.caption(
    "Power-user escape hatch over the run's local database. Pick a pre-built query "
    "to see how it works, then edit it and re-run."
)

run_dir = run_picker()
if run_dir is None:
    st.stop()

db_path = run_dir / "analysis.duckdb"
if not db_path.exists():
    st.warning("`analysis.duckdb` is missing in this run.")
    st.stop()


@st.cache_resource(show_spinner=False)
def get_con(path: str) -> duckdb.DuckDBPyConnection:
    """Open a read-only DuckDB connection at ``path`` and cache the handle.

    ``@st.cache_resource`` ensures the connection survives across Streamlit
    reruns instead of being reopened every time the user clicks something.
    Read-only mode is a safety belt: the SQL console is meant for
    exploration, so accidentally typing a destructive query errors out
    rather than mutating the database.

    Args:
        path: Filesystem path to the run's ``analysis.duckdb`` file as a
            string. Strings hash cleanly into the cache key.

    Returns:
        A read-only DuckDB connection. The caller is responsible for
        running queries; the connection is shared across reruns.
    """
    return duckdb.connect(path, read_only=True)


con = get_con(str(db_path))

tables = con.execute(
    "SELECT table_name, table_type FROM information_schema.tables ORDER BY 1"
).fetchdf()
st.caption(f"`{db_path.name}` has {len(tables)} tables and views.")

with st.expander("Schema browser", expanded=False):
    chosen_table = st.selectbox("Inspect table", tables["table_name"].tolist())
    schema = con.execute(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_name = ? ORDER BY ordinal_position",
        [chosen_table],
    ).fetchdf()
    st.dataframe(schema, width="stretch", hide_index=True)
    sample = con.execute(f'SELECT * FROM "{chosen_table}" LIMIT 10').fetchdf()
    st.dataframe(sample, width="stretch", hide_index=True)

# ---- Pre-canned queries -------------------------------------------------

st.subheader("Pre-built queries")
canned = {
    "Top managers by note evidence score": (
        "SELECT manager, tickets, avg_context_score, rich_or_forensic_share "
        "FROM manager_context_quality "
        "ORDER BY avg_context_score DESC"
    ),
    "Topics with highest unresolved share": (
        "SELECT issue_label, tickets, unresolved_share, recent_lift, recommended_action "
        "FROM opportunity_backlog "
        "WHERE tickets >= 50 "
        "ORDER BY unresolved_share DESC "
        "LIMIT 25"
    ),
    "Topics growing fast in the last 30 days": (
        "SELECT issue_label, last_30_tickets, recent_vs_prior_lift, recent_vs_prior_z, recent_unresolved_share "
        "FROM emerging_topics "
        "WHERE recent_vs_prior_lift > 1.5 AND last_30_tickets >= 10 "
        "ORDER BY emergence_score DESC"
    ),
    "Repeat customers with 5+ tickets": (
        "SELECT uid, persona, tickets, unresolved_share, avg_context_score, top_desires "
        "FROM repeat_user_personas "
        "WHERE tickets >= 5 "
        "ORDER BY tickets DESC "
        "LIMIT 50"
    ),
    "Money-risk topics in opportunity backlog": (
        "SELECT issue_label, tickets, trust_money_risk, unresolved_share, opportunity_score "
        "FROM opportunity_backlog "
        "WHERE trust_money_risk >= 0.4 "
        "ORDER BY opportunity_score DESC"
    ),
    "Tickets with the richest evidence": (
        "SELECT source_row, manager, primary_desire, context_depth_score, char_count, url_count, image_url_count "
        "FROM enriched_tickets "
        "WHERE context_depth_band IN ('rich', 'forensic') "
        "ORDER BY context_depth_score DESC "
        "LIMIT 50"
    ),
    "Counts of each evidence type (overall)": (
        "SELECT "
        "  SUM(CAST(has_url AS INT)) AS has_url, "
        "  SUM(CAST(has_image_url AS INT)) AS has_image_url, "
        "  SUM(CAST(has_timestamp AS INT)) AS has_timestamp, "
        "  SUM(CAST(has_room_or_group_id AS INT)) AS has_room_or_group_id, "
        "  SUM(CAST(has_long_uid_or_case_id AS INT)) AS has_long_uid_or_case_id, "
        "  SUM(CAST(has_ban_reason_language AS INT)) AS has_ban_reason_language, "
        "  SUM(CAST(has_user_claim AS INT)) AS has_user_claim, "
        "  SUM(CAST(has_money_terms AS INT)) AS has_money_terms, "
        "  SUM(CAST(has_status_or_svip_terms AS INT)) AS has_status_or_svip_terms, "
        "  SUM(CAST(has_multiline_note AS INT)) AS has_multiline_note "
        "FROM enriched_tickets"
    ),
}
chosen_query = st.selectbox("Pre-built query", ["(write my own)"] + list(canned.keys()))

initial_sql = canned.get(chosen_query, "SELECT * FROM enriched_tickets LIMIT 100")
sql = st.text_area("SQL", value=initial_sql, height=180)
run = st.button("Run query")

if run or chosen_query != "(write my own)":
    try:
        df = con.execute(sql).fetchdf()
        st.success(f"{len(df):,} rows returned.")
        st.dataframe(df, width="stretch", hide_index=True, height=520)
        st.download_button(
            "Download result as CSV",
            df.to_csv(index=False).encode("utf-8"),
            file_name="query_result.csv",
            mime="text/csv",
        )
    except Exception as exc:
        st.error(f"Query failed: {exc}")
