# 02 — Multipage apps

## What problem does this solve

A single Streamlit script becomes unmanageable past a few hundred lines.
The logical answer is multiple pages. Streamlit ships with a built-in
multipage convention so you don't have to invent a router yourself.

## What's actually happening

Streamlit's convention is a `pages/` folder next to your entry-point
script. Every `.py` file inside `pages/` becomes a page, and Streamlit
auto-builds a sidebar nav from the filenames.

The dashboard layout in this repository:

```
scripts/dashboard/
├── app.py                          # entry point, lives at /
├── lib.py                          # shared helpers (no page)
└── pages/
    ├── 01_Extraction_Progress.py   # /Extraction_Progress
    ├── 02_What_Users_Want.py       # /What_Users_Want
    ├── 03_Opportunities.py         # /Opportunities
    ├── 04_Manager_Note_Quality.py  # /Manager_Note_Quality
    ├── 05_Repeat_Customers.py      # /Repeat_Customers
    ├── 06_Ticket_Map.py            # /Ticket_Map
    ├── 07_Find_a_Ticket.py         # /Find_a_Ticket
    ├── 08_Browse_Data_Tables.py    # /Browse_Data_Tables
    ├── 09_Compare_Local_Models.py  # /Compare_Local_Models
    └── 10_Run_SQL_Queries.py       # /Run_SQL_Queries
```

`streamlit run scripts/dashboard/app.py` does the rest. The browser
opens at `localhost:8501/` showing `app.py`'s content; the sidebar
lists every page in `pages/` in numeric order.

## Naming conventions

Streamlit derives sidebar labels from filenames using a few rules:

- A leading number (`01_`, `02_`, etc.) sets sort order and is **stripped
  from the displayed label**. So `01_Extraction_Progress.py` shows up as
  "Extraction Progress" in the sidebar.
- Underscores in the filename become spaces. `What_Users_Want.py` becomes
  "What Users Want."
- Capitalisation stays as-is. Don't put `extraction_progress.py` and
  expect "Extraction Progress" — you'll get "extraction progress" in
  lower case.

Older guides recommend embedding emoji into filenames
(`01_📈_Extraction_Progress.py`); Streamlit will display the emoji as
the page icon. We don't do that here — the emoji-free filenames keep
the sidebar text clean.

## What goes in `lib.py`

`lib.py` is *not* a page. It's a regular Python module. Streamlit only
treats files inside `pages/` as pages; everything else is just a
Python file you can `import` from.

Each page imports from `lib.py` via:

```python
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))
from lib import maybe_load_csv, run_picker, ...
```

The two-line `sys.path.append` is required because Streamlit doesn't
add the parent directory to the path automatically — Python doesn't
know `pages/` is a sub-package, so a bare `from lib import ...` fails.
The fix: append the parent of the `pages/` folder (which is
`scripts/dashboard/`) to `sys.path`, then `from lib import ...` works.

Every page in this repo starts with that block. It's the price of
multipage Streamlit; once paid, you can share helpers across pages
freely.

## The page order matters

Streamlit sorts pages **alphabetically by filename**. The numeric
prefixes are how you control the sidebar order. Don't rely on file
modification time or anything else — alphabetical only.

The repo uses two-digit prefixes (`01_`, `02_`, ..., `10_`) so that
the sort is correct even past page 9. With single-digit prefixes,
`10_Run_SQL_Queries.py` would sort before `2_What_Users_Want.py`
(because the string `"1"` is lexicographically less than `"2"`). With
two-digit zero-padded prefixes, `10_` sorts after `09_` correctly.

## Sharing state across pages

Because every page is its own script, local variables don't carry
across pages. Two ways to share state:

1. **`st.session_state`** — covered in lesson 01. The dashboard stores
   the active run directory there:

   ```python
   st.session_state["run_dir"] = str(run_dir)
   ```

   Any page can read `st.session_state.get("run_dir")` to know which
   run to operate on.

2. **A helper that re-derives the value** — the dashboard's `run_picker()`
   in [scripts/dashboard/lib.py](../../scripts/dashboard/lib.py)
   regenerates the sidebar selectbox on every page. Each page calls
   `run_dir = run_picker()` independently, so the choice persists
   visually (Streamlit caches widget state by widget key) and the page
   gets the chosen run without explicit dict lookups.

Both patterns are used in this codebase. `run_picker()` is the
primary mechanism; `st.session_state["run_dir"]` is a secondary
write that pages don't currently read but could.

## Re-running a single page vs the whole app

Each page is its own script. When the user navigates to a page, that
file runs from the top. When they switch to another page, the new
file runs. The previous page's local variables are gone.

What does persist across page switches:

- Anything in `st.session_state`.
- The cache for `@st.cache_data` and `@st.cache_resource` (covered in
  lesson 04).
- Widget values that share a `key=` (Streamlit auto-keys most widgets
  by location, but you can force a key explicitly).

What doesn't persist:

- Local variables in any function or at the top level of a page script.
- The state of any object you constructed inside a page.
- The Plotly figure you just rendered.

## The Home page and `app.py`

The entry-point script `app.py` is the implicit "home" page. Its label
in the sidebar is whatever you set in `st.set_page_config(page_title=...)`
or the page's first `st.title()` call.

[scripts/dashboard/app.py](../../scripts/dashboard/app.py) sets
`page_title="What Users Want — Dashboard"` and the sidebar shows
"app" by default (Streamlit derives that from the filename). To change
the home label you can rename `app.py` to something like
`Home.py` — but doing that breaks our `run_dashboard.sh` script and
isn't worth it.

## Why we chose this approach

We considered four alternatives:

- **One huge script with `if page == "x":` branches.** Awkward past
  three pages. The branching gets buried in nested conditionals and
  shared state becomes a nightmare.
- **Custom router with `st.tabs`.** Tabs work for 3-5 sections on
  a single page; for 10 pages it's too much in one viewport.
- **Streamlit's `st.navigation` API** (newer Streamlit only). More
  flexible but requires programmatic page registration. The `pages/`
  folder convention is simpler and works with every Streamlit version
  we ship against.
- **`pages/` folder convention** — chosen. Adding a page is `touch
  pages/11_New_Thing.py` and Streamlit picks it up. No registration.

## Try it

Add a new page:

```bash
cat > scripts/dashboard/pages/11_Hello.py <<'EOF'
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))
from lib import run_picker
import streamlit as st

st.set_page_config(page_title="Hello", layout="wide")
st.title("Hello, multipage Streamlit")

run_dir = run_picker()
if run_dir is None:
    st.stop()

st.write(f"You picked: `{run_dir.name}`")
st.write(st.session_state)
EOF
```

The dashboard auto-detects the new file. Click "Hello" in the sidebar
nav. Notice that the run-picker dropdown is **already populated with
your last choice** because `run_picker()` is shared across pages.

Now rename the file to `99_Hello.py`. Save. Reload. The page moves
to the bottom of the sidebar — alphabetical sort confirmed.

Now delete the file:

```bash
rm scripts/dashboard/pages/99_Hello.py
```

Reload the browser. The page disappears from the sidebar within a
second.

That's the whole multipage system: file present means page exists,
file absent means page doesn't, prefix controls order.
