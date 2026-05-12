# 05 — Layouts

## What problem does this solve

A Streamlit page renders top-to-bottom by default. That's fine for a
form. It's wrong for a dashboard, where you want KPIs in a row, charts
side by side, secondary detail tucked away in a collapsible panel,
filters pinned to the side.

The Streamlit layout primitives are: `st.columns`, `st.tabs`,
`st.expander`, and `st.sidebar`. Combine them and you can build any
shape this codebase produces.

## What's actually happening

`st.columns(N)` returns N column objects. Anything you write to a
column (via `column.write(...)`, `column.metric(...)`, `with column:
...`) renders inside that column. The columns share the page width
equally by default.

`st.tabs([labels])` returns N tab objects. Same idea but only one
tab's content is visible at a time.

`st.expander(label, expanded=False)` is a collapsible disclosure block.
The body renders inside it; clicking the header toggles visibility.

`st.sidebar` is the left pane. Anything written to it via
`st.sidebar.X(...)` or inside a `with st.sidebar:` block lives there.

All four can nest. A column can contain tabs that contain expanders
that contain plotly charts. There's no theoretical limit; in practice
two levels deep is plenty.

## The code in this codebase

### KPI row with `st.columns`

[scripts/dashboard/app.py](../../scripts/dashboard/app.py):

```python
st.subheader("At a glance")
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Tickets analyzed", f"{len(enriched):,}" if enriched is not None else "—")
c2.metric("Unique users", f"{enriched['uid'].astype(...)}")
c3.metric("Tickets read by local AI", f"{len(extractions):,}" if extractions is not None else "0")
c4.metric("Discovered user wants", f"{(taxonomy['want_id'] != -1).sum() if 'want_id' in taxonomy.columns else len(taxonomy)}")
c5.metric("Ranked opportunities", f"{len(backlog):,}" if backlog is not None else "—")
```

`st.columns(5)` returns five column objects, unpacked into `c1` through
`c5`. Each gets a `.metric(...)` call. The five KPI cards render in a
row across the page.

`st.metric(label, value, delta)` renders a single KPI card with a label,
a big number, and an optional delta indicator. It's the right primitive
for "tiles at the top of a dashboard."

### Side-by-side comparison with two columns

[scripts/dashboard/pages/09_Compare_Local_Models.py](../../scripts/dashboard/pages/09_Compare_Local_Models.py):

```python
c_left, c_right = st.columns(2)
with c_left:
    left = st.selectbox("Left model", extraction_files, index=0, format_func=friendly_name)
with c_right:
    right_idx = 1 if len(extraction_files) > 1 else 0
    right = st.selectbox("Right model", extraction_files, index=right_idx, format_func=friendly_name)
```

The `with c_left:` and `with c_right:` blocks make every Streamlit call
inside them render in the corresponding column. This is how you get two
selectboxes on the same row.

### Tabs for multiple views of the same data

[scripts/dashboard/pages/02_What_Users_Want.py](../../scripts/dashboard/pages/02_What_Users_Want.py):

```python
tab1, tab2, tab3 = st.tabs(["Want × emotion", "Want × money risk", "Want × manager"])

with tab1:
    if "user_emotion" in filtered.columns:
        ct = pd.crosstab(filtered[heat_y_col], filtered["user_emotion"])
        fig = px.imshow(ct.values, ...)
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(ct, use_container_width=True)

with tab2:
    if "money_risk_level" in filtered.columns:
        ct = pd.crosstab(...)
        ...
```

Each `with tabN:` block is one tab's content. The user clicks tab
headers to switch; only the active tab is visible. Each tab can have
its own charts, tables, and widgets.

When to use tabs vs columns: tabs when only one view is interesting at
a time, columns when comparing both at once is the point.

### Expanders for secondary detail

[scripts/dashboard/app.py](../../scripts/dashboard/app.py):

```python
with st.expander("List of data tables", expanded=False):
    rows = []
    for name in csvs:
        path = run_dir / name
        rows.append(...)
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
```

`st.expander(label, expanded=False)` renders a collapsed disclosure
block by default. The user clicks to expand. The contents only render
once, but they don't take vertical space until expanded.

Use expanders for:

- File inventories that aren't the primary content.
- Schema browsers, metadata blocks, debug dumps.
- Single-ticket detail views (open-one-row patterns).
- Per-cluster summary tables when the chart is the headline.

### Sidebar for filters

Every filter widget in the dashboard lives in the sidebar. The
canonical pattern uses a `with st.sidebar:` block:

[scripts/dashboard/pages/03_Opportunities.py](../../scripts/dashboard/pages/03_Opportunities.py):

```python
with st.sidebar:
    st.header("Filters")
    if "recommended_action" in df.columns:
        actions = sorted(df["recommended_action"].dropna().unique())
        sel_actions = st.multiselect("Recommended action", actions, default=actions)
    if "tickets" in df.columns:
        min_tickets = st.slider("Minimum tickets in topic", 0, int(df["tickets"].max()) + 1, 0)
    ...
```

Every Streamlit call inside `with st.sidebar:` renders in the sidebar
panel. You can also use `st.sidebar.multiselect(...)` for a single call,
but the `with` block is cleaner when you have many widgets.

Sidebars stay visible while the main content scrolls — exactly what
filter widgets need.

## Adaptive sizing

Most layouts in this dashboard use `use_container_width=True`:

```python
st.dataframe(df, use_container_width=True, hide_index=True, height=520)
st.plotly_chart(fig, use_container_width=True)
```

This tells the widget to fill its column's full width. On a wide
monitor the table stretches; on a narrow window it compresses. Without
it, Streamlit picks a default width that may look cramped on either
extreme.

`height=520` for `st.dataframe` is fixed. Streamlit uses an internal
auto-height that's almost never right; setting an explicit height
gives a vertical scrollbar at the right place.

## Adaptive Plotly heights

Plotly figure heights need to adapt to content too. The pattern in
[scripts/dashboard/pages/02_What_Users_Want.py](../../scripts/dashboard/pages/02_What_Users_Want.py):

```python
fig = px.bar(
    counts_df(counts, "Want", "Tickets"),
    ...
    height=max(380, 28 * len(counts)),
)
```

`max(380, 28 * len(counts))` reserves ~28 pixels per bar with a 380px
floor. With 5 wants the chart is 380px; with 17 wants it's
476px. Without this formula you'd either crush 17 bars into 380px (text
overlapping) or stretch 5 bars across 1,000px (mostly empty).

## Why we chose this approach

The four primitives (columns, tabs, expanders, sidebar) cover every
layout this dashboard needs. We considered:

- **Streamlit `st.container` and `st.empty`** — useful for advanced
  patterns (live-updating regions, reserving space) but overkill for
  a static dashboard.
- **Custom HTML via `st.markdown(html, unsafe_allow_html=True)`** —
  technically possible but throws away Streamlit's responsive design.
  Not worth it for the time saved.
- **Sub-pages or modal dialogs** — Streamlit doesn't ship modals, and
  `pages/` is the right level of separation.

Sticking to the four primitives keeps every page consistent and
debuggable.

## Try it

Open the dashboard. Look at the home page (`app.py`) and notice five
KPI cards across the top — that's `st.columns(5)`.

Now open a Python file and reproduce a small layout:

```bash
cat > /tmp/layout_demo.py <<'EOF'
import streamlit as st
import pandas as pd

st.set_page_config(layout="wide")
st.title("Layout demo")

# 1. KPI row
c1, c2, c3 = st.columns(3)
c1.metric("Total", 100)
c2.metric("Done", 73, "+5")
c3.metric("Errors", 2, "-1", delta_color="inverse")

# 2. Two columns
left, right = st.columns(2)
with left:
    st.subheader("Left side")
    st.write("Some text on the left.")
with right:
    st.subheader("Right side")
    st.write("Some text on the right.")

# 3. Tabs
tab1, tab2 = st.tabs(["First", "Second"])
with tab1:
    st.write("Tab 1 content")
with tab2:
    st.write("Tab 2 content")

# 4. Expander
with st.expander("Click to see more"):
    st.write("Hidden by default.")
    st.dataframe(pd.DataFrame({"x": [1, 2, 3]}))

# 5. Sidebar
with st.sidebar:
    st.header("Filters")
    name = st.text_input("Name")
    age = st.slider("Age", 0, 100, 25)
    st.write(f"Hello {name}, age {age}")
EOF
.venv/bin/streamlit run /tmp/layout_demo.py
```

Open it in your browser. Notice:

- Three KPI cards in a row, each in its own column.
- Two side-by-side panels, each with its own subheader.
- Two tabs that switch when clicked.
- An expander that opens to reveal a small DataFrame.
- A sidebar with text input and slider that update the greeting live.

Every layout in the actual dashboard is built from these four
primitives, sometimes nested. Once you've seen this demo, every page
in `scripts/dashboard/pages/` reads at a glance.

Cleanup:

```bash
pkill -f layout_demo
rm /tmp/layout_demo.py
```
