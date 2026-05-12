# Exercise 04 — Add a dashboard page

## What you'll practice

- The Streamlit `pages/` folder convention.
- Importing helpers from `lib.py` correctly.
- Using `run_picker`, `maybe_load_csv`, `counts_df`.
- Building filters, charts, and a download button in one short page.

## The setup

You're adding a new page called **Daily Volume**. It will:

1. Read `enriched_tickets.csv` from the active run.
2. Plot a daily ticket-volume line chart.
3. Let users filter by manager and date range.
4. Show a sortable table of the daily counts.
5. Offer a CSV download.

This exercise touches every layer of module 09 and combines them in
a small, complete page.

## Step 1 — create the file

The naming convention is `NN_Page_Name.py` (Module 09 lesson 02).
Pages 01-10 already exist, so use `11_Daily_Volume.py`:

```bash
touch scripts/dashboard/pages/11_Daily_Volume.py
```

Streamlit will pick it up automatically the next time the dashboard
reloads.

## Step 2 — write the boilerplate

Open the file and write the standard preamble every page uses:

```python
"""Daily ticket volume — line chart, filters, table, download."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
from lib import maybe_load_csv, run_picker

st.set_page_config(page_title="Daily Volume", layout="wide")
st.title("Daily ticket volume")
st.caption(
    "Tickets received per day in the active run, with filters by manager "
    "and date range."
)

run_dir = run_picker()
if run_dir is None:
    st.stop()
```

The two-line `sys.path.append` is the Module 09 lesson 02 idiom for
making `from lib import ...` work inside a `pages/` file.

## Step 3 — load the data

```python
df = maybe_load_csv(run_dir, "enriched_tickets.csv")
if df is None:
    st.warning("`enriched_tickets.csv` is missing in this run.")
    st.stop()

df["date"] = pd.to_datetime(df["date_raw"], errors="coerce", dayfirst=True)
df = df.dropna(subset=["date"])
```

`pd.to_datetime(errors="coerce")` is the defensive parsing pattern
from Module 02. Tickets with unparseable dates are dropped.

## Step 4 — sidebar filters

```python
with st.sidebar:
    st.header("Filters")
    managers = sorted(df["manager"].fillna("Unknown").unique())
    sel_managers = st.multiselect("Manager", managers, default=managers)

    min_date, max_date = df["date"].min().date(), df["date"].max().date()
    date_range = st.date_input(
        "Date range",
        value=(min_date, max_date),
        min_value=min_date,
        max_value=max_date,
    )

f = df[df["manager"].fillna("Unknown").isin(sel_managers)]
if isinstance(date_range, tuple) and len(date_range) == 2:
    start, end = date_range
    f = f[(f["date"].dt.date >= start) & (f["date"].dt.date <= end)]
```

Two new widgets:

- `st.multiselect` — Module 09 lesson 03.
- `st.date_input` with a tuple default — produces a date *range*
  picker. The defensive `isinstance(date_range, tuple)` handles the
  case where the user picks a single date (would return a single
  `date` instead of a tuple).

## Step 5 — daily count and line chart

```python
daily = f.groupby(f["date"].dt.date).size().reset_index(name="tickets")
daily.columns = ["date", "tickets"]

st.subheader("Daily volume")
fig = px.line(daily, x="date", y="tickets", height=380)
fig.update_layout(margin=dict(l=10, r=10, t=10, b=10), xaxis_title="", yaxis_title="Tickets")
st.plotly_chart(fig, use_container_width=True)

st.metric("Total tickets in window", f"{daily['tickets'].sum():,}")
```

`groupby(f["date"].dt.date).size()` — group rows by the date portion
(stripping time), count rows per group. The `.dt.date` extracts the
date part of the datetime.

`px.line` is the line-chart equivalent of `px.bar`. Pass `x` and `y`
columns; Plotly handles the rest.

## Step 6 — sortable table

```python
st.subheader("Daily counts")
st.dataframe(
    daily.sort_values("date", ascending=False).rename(columns={"date": "Date", "tickets": "Tickets"}),
    use_container_width=True,
    hide_index=True,
    height=420,
)
```

Module 09 lesson 06 in action: rename for display, hide the index,
fixed height for predictable scroll.

## Step 7 — download button

```python
st.download_button(
    "Download daily counts as CSV",
    daily.to_csv(index=False).encode("utf-8"),
    file_name="daily_volume.csv",
    mime="text/csv",
)
```

## Step 8 — full file

The complete file should look like this:

```python
"""Daily ticket volume — line chart, filters, table, download."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
from lib import maybe_load_csv, run_picker

st.set_page_config(page_title="Daily Volume", layout="wide")
st.title("Daily ticket volume")
st.caption(
    "Tickets received per day in the active run, with filters by manager "
    "and date range."
)

run_dir = run_picker()
if run_dir is None:
    st.stop()

df = maybe_load_csv(run_dir, "enriched_tickets.csv")
if df is None:
    st.warning("`enriched_tickets.csv` is missing in this run.")
    st.stop()

df["date"] = pd.to_datetime(df["date_raw"], errors="coerce", dayfirst=True)
df = df.dropna(subset=["date"])

with st.sidebar:
    st.header("Filters")
    managers = sorted(df["manager"].fillna("Unknown").unique())
    sel_managers = st.multiselect("Manager", managers, default=managers)
    min_date, max_date = df["date"].min().date(), df["date"].max().date()
    date_range = st.date_input(
        "Date range",
        value=(min_date, max_date),
        min_value=min_date,
        max_value=max_date,
    )

f = df[df["manager"].fillna("Unknown").isin(sel_managers)]
if isinstance(date_range, tuple) and len(date_range) == 2:
    start, end = date_range
    f = f[(f["date"].dt.date >= start) & (f["date"].dt.date <= end)]

daily = f.groupby(f["date"].dt.date).size().reset_index(name="tickets")
daily.columns = ["date", "tickets"]

st.subheader("Daily volume")
fig = px.line(daily, x="date", y="tickets", height=380)
fig.update_layout(margin=dict(l=10, r=10, t=10, b=10), xaxis_title="", yaxis_title="Tickets")
st.plotly_chart(fig, use_container_width=True)

st.metric("Total tickets in window", f"{daily['tickets'].sum():,}")

st.subheader("Daily counts")
st.dataframe(
    daily.sort_values("date", ascending=False).rename(columns={"date": "Date", "tickets": "Tickets"}),
    use_container_width=True,
    hide_index=True,
    height=420,
)

st.download_button(
    "Download daily counts as CSV",
    daily.to_csv(index=False).encode("utf-8"),
    file_name="daily_volume.csv",
    mime="text/csv",
)
```

## Step 9 — verify

Save the file. The dashboard's hot reload picks it up:

```bash
./scripts/run_dashboard.sh
# Open http://localhost:8501
# Click "Daily Volume" in the sidebar
```

Expected behavior:

- The page title appears in the sidebar.
- A line chart of daily ticket counts shows up.
- The sidebar has a Manager multiselect and a date range picker.
- Filtering by manager updates the chart immediately.
- The table below the chart is sortable.
- The download button produces a CSV.

## Step 10 — verify the page lives in the navigation

The sidebar nav lists pages in alphabetical order. With the
two-digit prefix `11_`, your page appears after `10_Run_SQL_Queries.py`
— at the bottom of the list.

## Cleanup

If you don't want to keep the page, just delete the file:

```bash
rm scripts/dashboard/pages/11_Daily_Volume.py
```

The dashboard removes it from the sidebar within a second.

## What you learned

- Adding a Streamlit page is one new file; no registration, no router.
- Every page uses the same preamble (`sys.path.append`, `set_page_config`,
  `run_picker`).
- `pd.to_datetime(errors="coerce")` handles parse failures gracefully.
- `groupby(s.dt.date)` is the right way to bucket a datetime by day.
- `px.line` is the line-chart equivalent of `px.bar`.
- `st.date_input` with a tuple default produces a range picker.
- A complete page (data load + filters + chart + table + download) is
  ~50 lines.

## Stretch goals

If you want to push the exercise further:

1. **Add a "compare to baseline" overlay** — compute the rolling
   30-day average and add it as a second line on the chart.
2. **Add a tab for weekly / monthly aggregation** — `st.tabs(["Daily",
   "Weekly", "Monthly"])` with each tab using a different `groupby`
   resolution.
3. **Add a DuckDB-backed query** — instead of loading the CSV into
   pandas, use `duckdb.connect(read_only=True)` and run an aggregated
   SQL query directly. (Module 09 lesson 04 covered the cache
   decorator; Module 07 covered DuckDB.)

Each stretch goal touches a different module's content.
