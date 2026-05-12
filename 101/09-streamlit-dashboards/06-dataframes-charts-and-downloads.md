# 06 — DataFrames, charts, and downloads

## What problem does this solve

You have data, you have a chart, and you want users to be able to take
a copy with them. Streamlit gives you three primitives to wrap up:
`st.dataframe` for tabular display, `st.plotly_chart` for interactive
charts, and `st.download_button` for exports. Every page in this
dashboard uses all three.

## What's actually happening

Each primitive is a one-liner that takes a Python object and renders
the right widget.

- **`st.dataframe(df)`** renders a DataFrame as an interactive table:
  sortable column headers, scrollable, copy-paste support.
- **`st.plotly_chart(fig)`** embeds a Plotly figure with all its
  interactivity (zoom, pan, hover, legend toggling).
- **`st.download_button(label, data, file_name, mime)`** renders a
  button that triggers a real browser download when clicked.

These three cover 90% of what users want to *do* with data on a
dashboard: read it, see it visualized, take it home.

## The code in this codebase

### `st.dataframe` — interactive table

[scripts/dashboard/pages/02_What_Users_Want.py](../../scripts/dashboard/pages/02_What_Users_Want.py):

```python
display_taxonomy = taxonomy[cols_to_show].copy()
for col in ["share", "high_money_risk_share", "high_trust_risk_share"]:
    if col in display_taxonomy.columns:
        display_taxonomy[col] = (display_taxonomy[col] * 100).round(1).astype(str) + "%"
display_taxonomy = display_taxonomy.rename(columns=rename_map)
st.dataframe(display_taxonomy, use_container_width=True, hide_index=True, height=380)
```

Three things matter in that call:

- **`use_container_width=True`** stretches the table to fill its column.
  Without this Streamlit picks a narrow default width and the right
  half of the page is empty.
- **`hide_index=True`** hides the pandas row index column. The index is
  almost always meaningless to end users (just integers 0, 1, 2...),
  and showing it eats horizontal space.
- **`height=380`** sets a fixed pixel height. Streamlit's auto-height
  is usually wrong — too tall on small tables, too short on big ones.
  An explicit height gives a vertical scrollbar at the right place.

### Display-only column renames

The dashboard pattern is: keep internal column names (snake_case,
machine-friendly) in the DataFrame, but rename them just before
rendering:

```python
rename_map = {
    "want_title": "Want",
    "want_summary": "What this cluster is about",
    "size": "Tickets",
    "share": "Share of analyzed tickets",
    "top_jobs": "Top jobs to be done",
    ...
}
display_taxonomy = taxonomy[cols_to_show].copy().rename(columns=rename_map)
st.dataframe(display_taxonomy, ...)
```

Why a copy: if you `rename` in place on the original DataFrame, every
subsequent code path that reads `taxonomy["want_title"]` breaks. The
copy keeps internal names internal.

Why a dict literal instead of a dict comprehension: explicit beats
clever. A future reader sees exactly which columns get renamed to what.

### Display-time formatting

Probability columns are stored as floats in `[0, 1]` — that's the
sensible internal format. For display, multiply by 100 and add a
`%` sign:

```python
display_taxonomy["share"] = (display_taxonomy["share"] * 100).round(1).astype(str) + "%"
```

Three operations chained:

1. `* 100` — convert to percentage scale.
2. `.round(1)` — one decimal place is plenty for shares.
3. `.astype(str) + "%"` — coerce to string and append the percent sign.

After this transformation the column is no longer numeric — it's
strings like `"34.7%"`. That's intentional: the goal is human-readable
display, not further computation.

### `st.plotly_chart` — interactive charts

```python
fig = px.bar(...)
fig.update_layout(margin=dict(l=10, r=10, t=10, b=10), yaxis={"categoryorder": "total ascending"})
st.plotly_chart(fig, use_container_width=True)
```

Build the figure with Plotly Express (lesson 02 in module 08), tweak
its layout, then hand it to `st.plotly_chart`. The chart inherits
every interactive feature Plotly provides: zoom, pan, hover tooltips,
legend toggling, the export-to-PNG button in the toolbar.

`use_container_width=True` is the same idea as for tables — fill the
column.

### `st.download_button` — let users take data home

[scripts/dashboard/pages/07_Find_a_Ticket.py](../../scripts/dashboard/pages/07_Find_a_Ticket.py):

```python
st.download_button(
    "Download these rows as CSV",
    df.to_csv(index=False).encode("utf-8"),
    file_name="filtered_tickets.csv",
    mime="text/csv",
)
```

Four arguments:

- **Label** — the button text.
- **Data** — the bytes to download. `df.to_csv(index=False)` returns a
  string; `.encode("utf-8")` turns it into bytes. (`index=False` keeps
  the meaningless integer row index out of the export.)
- **`file_name=`** — the filename the user will see in their download.
- **`mime=`** — the MIME type. `text/csv` is right for CSV;
  `application/json` for JSON; `application/octet-stream` for
  binary blobs.

Streamlit handles the rest: when the user clicks, the bytes are sent as
a download.

The same pattern in
[scripts/dashboard/pages/10_Run_SQL_Queries.py](../../scripts/dashboard/pages/10_Run_SQL_Queries.py):

```python
st.download_button(
    "Download result as CSV",
    df.to_csv(index=False).encode("utf-8"),
    file_name="query_result.csv",
    mime="text/csv",
)
```

Identical idiom. Anywhere a DataFrame ends up on screen, a download
button next to it costs nothing and gives the user a real export.

## Putting them together

Every page in this dashboard ends with the same three things:

1. Render charts (`st.plotly_chart`).
2. Render the underlying table (`st.dataframe`).
3. Offer a download (`st.download_button`).

The pattern is so consistent it functions as a UX promise: when you
land on a dashboard page, you can always get to the numbers. Charts
without their underlying tables hide information; tables without
charts hide trends; both without an export trap users.

## Why we chose this approach

We had three alternatives for table display:

- **`st.table`** — renders a non-interactive HTML table. Smaller,
  static, doesn't scroll. Good for tiny lookup tables; wrong for
  anything past 20 rows.
- **`st.dataframe`** — interactive, sortable, scrollable. The right
  default for "here's a result table" anywhere in this dashboard.
- **`st.data_editor`** — Streamlit's editable table, would let users
  modify rows in place. Useful for forms/CRUD, overkill for a
  read-only dashboard.

For charts:

- **Matplotlib via `st.pyplot(fig)`** — works but loses interactivity.
  We use `st.pyplot` only for static reports.
- **Plotly via `st.plotly_chart(fig)`** — what we use for everything
  in the dashboard. Already covered in module 08.

For downloads:

- **`st.download_button`** is the only sensible primitive. The
  alternative is dropping a temporary file on disk and exposing a
  link, which works but doesn't scale to multiple users.

## Try it

Open the SQL Console page (`Run SQL queries` in the sidebar). Run any
canned query. Notice three things:

1. The result table renders with sortable columns, scrollable rows,
   row count in the header.
2. Click any column header to sort by it. Click again to reverse.
   Streamlit is doing this client-side.
3. The "Download result as CSV" button below the table. Click it; your
   browser saves `query_result.csv`. Open it — it's the exact same
   data minus the row index.

Now reproduce the pattern in a tiny standalone script:

```bash
cat > /tmp/df_demo.py <<'EOF'
import streamlit as st
import pandas as pd
import plotly.express as px

st.set_page_config(layout="wide")
st.title("DataFrame, chart, download demo")

df = pd.read_csv("outputs/option2_20260502_150055/manager_context_quality.csv")

# Display the table with column renames
display = df.rename(columns={
    "manager": "Manager",
    "tickets": "Tickets",
    "avg_context_score": "Avg note evidence score",
})
st.dataframe(display, use_container_width=True, hide_index=True, height=300)

# Render a chart
fig = px.bar(
    df.sort_values("avg_context_score", ascending=True),
    x="avg_context_score",
    y="manager",
    orientation="h",
)
st.plotly_chart(fig, use_container_width=True)

# Offer a download of the *displayed* version
st.download_button(
    "Download displayed table as CSV",
    display.to_csv(index=False).encode("utf-8"),
    file_name="manager_quality.csv",
    mime="text/csv",
)
EOF
.venv/bin/streamlit run /tmp/df_demo.py
```

Click the download button, save the file, open it in any editor.
You'll see the renamed columns ("Manager", "Tickets", "Avg note
evidence score"), confirming that the download captures whatever you
display. Internal names stayed internal; users got friendly names.

Cleanup:

```bash
pkill -f df_demo
rm /tmp/df_demo.py
```
