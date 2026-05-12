# 03 — Widgets and state

## What problem does this solve

You need users to filter, choose, search, type, and click. Without widgets
your dashboard is a static report. Streamlit's widget API turns each
interaction into a Python value you can use immediately — no callbacks,
no event handlers.

## What's actually happening

Every Streamlit widget is a function that **returns the current widget
value** every time the script runs. When the user changes the widget,
Streamlit reruns the script (lesson 01) and the widget function returns
the new value.

That single rule covers every interaction:

```python
slider_value = st.slider("Pick a number", 0, 100, 50)
# On first render: slider_value == 50
# After user drags to 75: slider_value == 75 on the next rerun
```

You write the script as if the widget had already been configured to
the right value. Streamlit handles the loop.

## Widgets used in this codebase

### `st.selectbox` — pick one from a list

[scripts/dashboard/lib.py](../../scripts/dashboard/lib.py) `run_picker()`:

```python
def run_picker(label: str = "Run directory") -> Path | None:
    runs = list_runs()
    if not runs:
        st.error(f"No option2_* run directories found under {OUTPUTS_DIR}.")
        return None
    options = {run_label(r): r for r in runs}
    default_label = next(iter(options))
    sel = st.sidebar.selectbox(label, list(options.keys()), index=0)
    return options.get(sel, runs[0])
```

The pattern:

1. Build a dict mapping display labels to underlying values.
2. Pass `list(options.keys())` to `st.selectbox` — these are the strings
   the user sees.
3. Resolve the chosen label back to its underlying value via the dict.

`index=0` sets the default selection (first option). `st.sidebar.selectbox`
puts the widget in the sidebar instead of the main column.

### `st.multiselect` — pick multiple

[scripts/dashboard/pages/02_What_Users_Want.py](../../scripts/dashboard/pages/02_What_Users_Want.py):

```python
emotions = sorted(assignments["user_emotion"].dropna().unique())
sel_emotions = st.multiselect("User emotion", emotions, default=emotions)
```

`st.multiselect(label, options, default)` returns a *list* of selected
values. Passing `default=options` selects everything by default — the
user has to deselect to filter.

### `st.slider` — numeric range

```python
money_min, money_max = st.slider("Money risk (1 low — 5 high)", 1, 5, (1, 5))
```

When you pass a 2-tuple as the default, Streamlit returns a 2-tuple
unpacked as `(min, max)`. That's a range slider. Pass a single number
and you get a single-value slider.

[scripts/dashboard/pages/06_Ticket_Map.py](../../scripts/dashboard/pages/06_Ticket_Map.py):

```python
sample_n = st.slider(
    "How many dots to show (smaller = faster)",
    500,
    len(assignments),
    min(3000, len(assignments)),
    step=500,
)
```

`step=500` constrains the slider to multiples of 500.

### `st.text_input` — text entry

```python
text_query = st.text_input("Text contains", placeholder="dealer, scam, channel, разблокир...")
```

Returns the current contents as a string. `placeholder=` is the gray
hint shown when the field is empty.

### `st.checkbox` — boolean toggle

[scripts/dashboard/pages/01_Extraction_Progress.py](../../scripts/dashboard/pages/01_Extraction_Progress.py):

```python
refresh = st.sidebar.checkbox("Auto-refresh every 5s", value=True)
```

Returns `True` or `False`. `value=True` sets the default state.

### `st.button` — one-shot action

[scripts/dashboard/pages/10_Run_SQL_Queries.py](../../scripts/dashboard/pages/10_Run_SQL_Queries.py):

```python
run = st.button("Run query")
if run or chosen_query != "(write my own)":
    df = con.execute(sql).fetchdf()
    st.dataframe(df, use_container_width=True)
```

A button returns `True` only on the rerun caused by clicking it; on the
next rerun (e.g. caused by changing some other widget) it's back to
`False`. Use this to gate "execute now" actions.

### `st.download_button` — let the user save data

```python
st.download_button(
    "Download these rows as CSV",
    df.to_csv(index=False).encode("utf-8"),
    file_name="filtered_tickets.csv",
    mime="text/csv",
)
```

The second argument is the bytes to download. `df.to_csv(index=False)`
returns a string; `.encode("utf-8")` turns it into bytes. Streamlit
renders a button that produces a real download link in the user's
browser.

## The filter pattern

Every page in the dashboard uses the same filter pattern:

1. Load the data unfiltered.
2. Open `with st.sidebar:` and define a widget for every filter
   dimension.
3. Build a filtered copy: `f = df.copy()` then narrow it with each
   widget's value.
4. Render charts and tables off `f`.

[scripts/dashboard/pages/03_Opportunities.py](../../scripts/dashboard/pages/03_Opportunities.py):

```python
with st.sidebar:
    st.header("Filters")
    sel_actions = st.multiselect("Recommended action", actions, default=actions)
    min_tickets = st.slider("Minimum tickets in topic", 0, int(df["tickets"].max()) + 1, 0)
    min_unresolved = st.slider("Minimum unresolved share", 0.0, 1.0, 0.0, step=0.05)
    ...

f = df.copy()
if sel_actions is not None and "recommended_action" in f.columns:
    f = f[f["recommended_action"].isin(sel_actions)]
if "tickets" in f.columns:
    f = f[f["tickets"] >= min_tickets]
if "unresolved_share" in f.columns:
    f = f[f["unresolved_share"] >= min_unresolved]
```

The `with st.sidebar:` block puts every widget in the left sidebar.
The `f = df.copy()` then sequential narrowing is the standard pandas
filter chain — none of it is Streamlit-specific. Streamlit's role is
just feeding live values into normal pandas code.

## Widget keys and `st.session_state`

By default Streamlit assigns each widget an internal key based on its
type, label, and order in the script. That's enough for most cases.

When you have two widgets with the same label on the same page (rare but
possible), set an explicit key:

```python
left = st.selectbox("Model", files, key="left_model")
right = st.selectbox("Model", files, key="right_model")
```

Once a widget has a key, its current value lives at
`st.session_state[key]`. You can read and write it directly:

```python
st.session_state["left_model"] = "ollama_gemma3-4b_extractions.csv"
```

Setting the value before the widget is rendered changes the widget's
default. Setting it after has no immediate effect on the widget's
display until the next rerun.

## Why we chose this approach

The widget-as-function-call pattern is Streamlit's killer feature. It
lets the page read like ordinary Python while still being interactive.
Compare a typical Dash equivalent:

- Dash: define the widget as a `Component`, register a callback with
  `@app.callback(Output(...), Input(...))`, write the callback function
  to recompute the chart, return the new figure.
- Streamlit: `slider_value = st.slider(...)`. Use `slider_value`
  immediately. Rerun handles the rest.

For an internal dashboard the Streamlit version is half the code and
easier to debug. You give up some control over partial updates (Dash
only re-renders the affected component; Streamlit re-renders the
whole page) but for a dataset of our size that doesn't matter.

## Try it

Open the dashboard, navigate to the Find a Ticket page, and watch the
filter chain:

1. Type "diamond" into the **Text contains** box. Notice the result
   table reduces to ~140 rows immediately.
2. Add **Albert** to the manager filter. The count drops further.
3. Set the **Note evidence level** filter to `forensic`. The count
   drops again.

Each interaction triggers a full page rerun. Each rerun re-executes
the SQL and re-renders the table. With 6,728 rows and DuckDB this is
imperceptible; with 10 million rows you'd need caching (lesson 04) or
server-side filters (lesson 06 in module 07).

Now break it deliberately. In a fresh terminal:

```bash
cat > scripts/dashboard/pages/99_BadFilter.py <<'EOF'
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))
import streamlit as st
import pandas as pd

n = st.slider("How many", 1, 10, 5)
df = pd.DataFrame({"x": list(range(n))})
st.dataframe(df, use_container_width=True)
EOF
```

Open the page. Drag the slider — the dataframe re-renders instantly.

Add a print statement at the top:

```python
print(f"DEBUG: page rerun, slider = {n}")
```

Save. Drag the slider again. Watch the dashboard's terminal — every
slider change prints a new debug line. That's the entire script
re-running. Once you see this, the rerun model becomes intuitive.

Cleanup:

```bash
rm scripts/dashboard/pages/99_BadFilter.py
```
