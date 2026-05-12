# 01 — The Streamlit mental model

## What problem does this solve

Building a web UI in Python normally means writing routes, templates,
session middleware, and JavaScript. For a quick internal dashboard
that's all overhead. You want: **read a CSV, filter it, show a chart,
let the user change a slider**. Every line that isn't one of those is
distraction.

Streamlit solves this by making one radical decision: **your script
runs top to bottom, every time the user interacts**. There is no event
loop. There is no `if request.method == "POST"`. There is no callback
hell. You write a script as if you were running it once, and Streamlit
re-runs it whenever the user touches a widget.

## What's actually happening

When you launch `streamlit run scripts/dashboard/app.py`, Streamlit
spins up a small web server and points the browser at it. The server
loads your script and runs it once, top to bottom, capturing every
`st.*` call as an instruction to render some HTML/JS. The result is
sent to the browser.

When the user clicks a slider, picks an option, or types in a text
input, the browser sends the new widget state back to the server.
Streamlit then **re-runs the entire script from the top**, this time
with the slider returning the new value. The output is sent back to
the browser, which diffs and updates only the parts that changed.

This is unusual the first time you see it. Variables you defined at
the top of the script are recomputed every time. Anything you do not
want recomputed has to live behind a cache decorator (covered in
lesson 04). The mental shift is *"my script is a pure function of
widget state."*

The second consequence: there is no callback to register. If the user
moves a slider, the *entire script reruns*. This sounds wasteful and
sometimes is, but Streamlit is very fast, and the design simplification
is enormous.

## The code in this codebase

The home page [scripts/dashboard/app.py](../../scripts/dashboard/app.py)
is a perfect example of "a script you can read top to bottom":

```python
import streamlit as st
from lib import OUTPUTS_DIR, run_picker, maybe_load_csv, ...

st.set_page_config(
    page_title="What Users Want — Dashboard",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("What Users Want — analysis dashboard")
st.caption("Live, filterable view ...")

run_dir = run_picker()
if run_dir is None:
    st.stop()
st.session_state["run_dir"] = str(run_dir)

st.markdown(f"**Active run folder:** `{run_dir.name}`")

enriched = maybe_load_csv(run_dir, "enriched_tickets.csv")
extractions = _first_existing("ollama_gemma3-4b_extractions.csv", "llm_extractions.csv")
taxonomy = maybe_load_csv(run_dir, "user_wants_taxonomy.csv")

st.subheader("At a glance")
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Tickets analyzed", f"{len(enriched):,}" if enriched is not None else "—")
# ... more KPI cards
```

Read this as a recipe. The script:

1. Imports Streamlit and the project's `lib` helpers.
2. Calls `st.set_page_config(...)` — this **must be the first
   Streamlit call** in the script. It configures the browser tab and
   page layout. Putting any other `st.*` call before it raises an error.
3. Renders the page title and caption.
4. Calls `run_picker()` (a sidebar selectbox helper from `lib.py`) to
   let the user pick which `outputs/option2_<timestamp>` directory to
   analyze.
5. Calls `st.stop()` if no run was picked. This halts the script
   immediately — Streamlit treats "stopped" pages gracefully and
   doesn't try to render anything else.
6. Stores the run choice in `st.session_state["run_dir"]` so other
   pages can read it.
7. Loads three CSVs from the chosen run.
8. Renders five KPI cards using `st.columns(5)` and `c1.metric(...)`.

Every time the user changes the run-picker dropdown, **all eight
steps run again** with the new selection.

## Session state — the one piece of persistence

Because the script runs top to bottom on every interaction, normal
Python variables are not persistent between reruns. If the user picks
"Albert" in a multiselect and then clicks somewhere else, the
multiselect-state survives because Streamlit knows about it; but a
local variable like `selected_manager = "Albert"` would be reset on
every rerun if it weren't bound to a widget.

For state that needs to live across reruns *and* across pages, use
**`st.session_state`**. It's a dict-like object scoped to the user's
browser session.

[scripts/dashboard/app.py](../../scripts/dashboard/app.py):

```python
st.session_state["run_dir"] = str(run_dir)
```

That single line writes the chosen run directory into the session state.
On every other page (Find a Ticket, What Users Want, etc.), that key
will still be there, regardless of how many reruns happen in between.

You can also read from `st.session_state` to set an initial value for
a widget on first render:

```python
default_run = st.session_state.get("run_dir")
sel = st.sidebar.selectbox("Run directory", options, index=options.index(default_run) if default_run in options else 0)
```

## The "stop and tell the user" pattern

Streamlit pages frequently need to bail out early — missing inputs,
empty dataframes, the run directory hasn't been built yet. The pattern:

```python
if taxonomy is None or assignments is None:
    st.warning(
        "This run does not have a discovered taxonomy yet. "
        "Run `scripts/build_user_wants_taxonomy.py outputs/<run_dir>` to generate it."
    )
    st.stop()
```

`st.warning(...)` renders a yellow box. `st.stop()` halts the script.
Together they form a graceful failure: the user sees what's missing
and knows what command to run, instead of a stack trace.

## Why we chose this approach

We picked Streamlit over Dash, Panel, FastAPI+React, and Gradio because:

- **Lowest cost per page**: a new page is one new file under
  `pages/`. No router, no template, no JSX.
- **Hot reload**: edit a file, save, the browser refreshes
  automatically. No build step.
- **Python-only**: every team member who can write a Jupyter
  notebook can write a dashboard page.
- **The rerun model**: it sounds weird the first time you hear about
  it, but it eliminates entire categories of bugs (state inconsistency,
  callback ordering, race conditions). For an internal dashboard with
  a handful of users the simplicity wins.

We give up:

- **Performance ceiling**: Streamlit isn't suitable for 1,000 concurrent
  users. We're not building one.
- **Custom JS**: hard to embed arbitrary JavaScript widgets. Plotly
  covers most cases.
- **Complex routing**: a multi-step wizard with deep state is
  awkward. We're not building one.

## Try it

Run the dashboard:

```bash
./scripts/run_dashboard.sh
```

Open [http://localhost:8501](http://localhost:8501). Now:

1. Open a terminal and tail `/tmp/streamlit.log` (or the terminal where
   the dashboard is running). Click the run-picker dropdown and pick a
   different run. Watch the log lines — every interaction triggers a
   rerun of the script.

2. Edit `scripts/dashboard/app.py`. Change the title to something
   silly. Save the file. The browser tab automatically reloads with
   the new title within ~1 second. This is hot reload, free.

3. Add a new line:
   `st.write(st.session_state)` somewhere on the page. Save. Reload.
   You'll now see the session state dictionary printed live. Watch
   how it changes as you interact with widgets on other pages.

4. Now break it deliberately: put `st.title("Test")` *before*
   `st.set_page_config(...)`. Save. The browser shows
   `StreamlitAPIException: set_page_config() can only be called once
   per app page, and must be called as the first Streamlit command in
   your script.` — which is exactly what we said earlier.

The mental shift to "my script is a pure function of widget state"
takes about an hour. Once it clicks, the rest of the framework follows
naturally.
