# 04 — Caching

## What problem does this solve

Streamlit reruns your script on every interaction. A page that loads a
4 MB CSV from disk on every rerun is fine for one user; a page that
embeds 6,728 ticket strings on every rerun is unusable. You need to
**memoize expensive computations** so they run once per (input set) and
return instantly thereafter.

Streamlit ships two cache decorators: `@st.cache_data` and
`@st.cache_resource`. They look interchangeable but solve different
problems. Picking the wrong one produces subtle bugs.

## What's actually happening

Both decorators do the same high-level thing: turn a function into one
that remembers its results.

The difference is **what they remember**.

- **`@st.cache_data`** is for **immutable values** — DataFrames, lists,
  dicts, strings, numpy arrays. The cache stores a *copy* of the return
  value. Each subsequent call with the same args returns a fresh copy.
  Copies prevent one consumer from accidentally mutating another's data.

- **`@st.cache_resource`** is for **shared, mutable, long-lived
  resources** — database connections, ML models, file handles, HTTP
  sessions. The cache stores the *original object*. Every caller
  receives the same instance. No copy.

If you cache a DuckDB connection with `@st.cache_data`, Streamlit will
try to copy it and either fail or produce a useless duplicate. If you
cache a DataFrame with `@st.cache_resource`, every page mutating it
will affect every other page.

## How to pick

Ask: "if two callers got this back at the same time, would they want
their own copy or the same instance?"

| Returned thing | Decorator | Why |
|---|---|---|
| DataFrame | `cache_data` | Pandas operations may mutate; isolation is safer |
| List/dict/string | `cache_data` | Immutable for our purposes |
| numpy array | `cache_data` | Same as DataFrame |
| DuckDB connection | `cache_resource` | A connection is shared infrastructure |
| Loaded sklearn model | `cache_resource` | Loading is expensive, the model is read-only |
| Open file handle | `cache_resource` | Not copyable |
| HTTP session | `cache_resource` | Same as connection |

## The code in this codebase

[scripts/dashboard/lib.py](../../scripts/dashboard/lib.py) caches
multiple data lookups:

```python
@st.cache_data(show_spinner=False)
def list_csvs(run_dir_str: str) -> list[str]:
    return sorted(p.name for p in Path(run_dir_str).glob("*.csv"))


@st.cache_data(show_spinner=False)
def list_other_files(run_dir_str: str) -> dict[str, list[str]]:
    run_dir = Path(run_dir_str)
    return {
        "json": sorted(p.name for p in run_dir.glob("*.json")),
        ...
    }


@st.cache_data(show_spinner=False)
def load_csv(run_dir_str: str, name: str) -> pd.DataFrame:
    path = Path(run_dir_str) / name
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


@st.cache_data(show_spinner=False)
def load_json(run_dir_str: str, name: str) -> dict[str, Any] | None:
    ...
```

Every one of these returns a value (a list, a dict, a DataFrame). They
all use `cache_data`.

The connection helper is different.
[scripts/dashboard/pages/07_Find_a_Ticket.py](../../scripts/dashboard/pages/07_Find_a_Ticket.py):

```python
@st.cache_resource(show_spinner=False)
def get_con(run_dir_str: str) -> duckdb.DuckDBPyConnection:
    db_path = Path(run_dir_str) / "analysis.duckdb"
    if db_path.exists():
        return duckdb.connect(str(db_path), read_only=True)
    con = duckdb.connect()
    con.execute(
        f"CREATE VIEW enriched_tickets AS SELECT * FROM read_csv_auto('{Path(run_dir_str) / 'enriched_tickets.csv'}', HEADER=True)"
    )
    return con
```

The function returns a database connection. We use `cache_resource`
because:

1. We don't want to copy it. There's no meaningful "copy of a DuckDB
   connection."
2. The connection is shared. Every page that uses this helper gets the
   same connection.

The same pattern is in
[scripts/dashboard/pages/10_Run_SQL_Queries.py](../../scripts/dashboard/pages/10_Run_SQL_Queries.py):

```python
@st.cache_resource(show_spinner=False)
def get_con(path: str) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(path, read_only=True)
```

## Cache key — what makes a hit

A cache hit happens when the function is called with **the same
argument values** as a previous call. Streamlit hashes the arguments
to build a key.

This means:

- `list_csvs("/path/to/run_A")` and `list_csvs("/path/to/run_B")` are
  different cache entries.
- Switching the run-picker to a new run produces a cache miss for that
  run, then hits for every subsequent call until you switch again.
- Switching back to the old run is a cache hit — no disk read.

The hash function works on hashable Python types: strings, ints,
floats, tuples of those. **Pandas DataFrames are not hashable by
default**, so you can't pass a DataFrame as an argument and expect
caching to work — Streamlit will warn.

The convention in this repo: pass `run_dir_str: str` instead of
`run_dir: Path` to cached functions. Strings hash cleanly. The
function converts the string back to a Path internally.

## `show_spinner=False`

By default Streamlit shows a spinner ("Running list_csvs...") while a
cached function executes for the first time on a given input. The
spinner is helpful for slow operations (a 30-second model load) and
distracting for fast ones (a 50-millisecond directory scan).

Every cached function in this repo passes `show_spinner=False`. They're
all fast. The first call is the only call that runs the body; we don't
need to telegraph that.

## Cache invalidation

The Streamlit cache is process-scoped: it lives until the Streamlit
server restarts. There are three ways to clear it:

1. **Restart the server.** Stop with `pkill -f "streamlit run"`,
   restart with `./scripts/run_dashboard.sh`. All caches die.
2. **Hot-reload while editing the function.** Saving a file that
   contains a cached function invalidates that function's cache only.
3. **Clear from the UI.** Streamlit's hamburger menu (top right) has a
   "Clear cache" option. Useful during demos.

We don't use TTL or size-based eviction. The dashboard's working set
is small enough that cache size never matters.

## Why we chose this approach

Two cache decorators is more API surface than the previous Streamlit
recommendation (a single `@st.cache` that did both). The split was
introduced specifically because users were confused about copy
semantics. Now the choice is explicit:

- "I'm returning *data*" → `cache_data`.
- "I'm returning a *thing*" → `cache_resource`.

For the dashboard this works perfectly: every CSV/JSON loader is
`cache_data`; every database connection is `cache_resource`.

## Try it

Drop a print statement into a cached function to watch the cache hit
rate.

```bash
cat > /tmp/cache_demo.py <<'EOF'
import streamlit as st
import time

@st.cache_data(show_spinner=False)
def slow_function(x: int) -> int:
    print(f"DEBUG: computing slow_function({x})")
    time.sleep(2)
    return x * 2

x = st.slider("Pick x", 1, 10, 5)
result = slow_function(x)
st.write(f"Result: {result}")
EOF

.venv/bin/streamlit run /tmp/cache_demo.py
```

Move the slider from 5 → 6 → 7 → 6 → 5. Watch the terminal.

You'll see "DEBUG: computing slow_function(5)" the first time, then
"DEBUG: computing slow_function(6)" when you move to 6, then
"DEBUG: computing slow_function(7)" at 7. When you move *back* to 6,
no debug line — that's a cache hit, instant return. Same for 5.

Now change the function to return a DataFrame and observe that the
copy isolation works:

```python
import pandas as pd

@st.cache_data(show_spinner=False)
def get_df(n: int) -> pd.DataFrame:
    print(f"DEBUG: building df({n})")
    return pd.DataFrame({"x": list(range(n))})

n = st.slider("Pick n", 1, 10, 5)
df = get_df(n)
df["new_col"] = df["x"] * 2  # mutate the returned DataFrame
st.dataframe(df)
```

Slide back and forth. Even though we mutated `df`, the next cache hit
returns a fresh copy of the original DataFrame. Mutations don't
persist. That's the safety net `cache_data` gives you.

Now change `@st.cache_data` to `@st.cache_resource` and re-run.
Suddenly mutations *do* persist between reruns — every "rerun" hands
you the same instance. That's the wrong behavior for a DataFrame and
exactly why this isn't the right decorator for data.

Cleanup:

```bash
pkill -f "cache_demo.py"
rm /tmp/cache_demo.py
```
