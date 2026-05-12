# Decorators, Closures, and CLI

## The problem

Streamlit reruns each page top-to-bottom on every user click. That means
your `pd.read_csv` call fires every time the user picks a new dropdown
value. On a 6,728-row CSV that's already too slow; on a multi-megabyte
DuckDB connection that's fatal — you'd reopen the database file on every
keystroke.

You need a way to say: "compute this *once* per unique argument set, then
cache the result for the rest of the session." That is what decorators
provide. The dashboard uses two flavours of Streamlit's caching decorator
(`@st.cache_data` for values, `@st.cache_resource` for handles), and the
home page uses a closure to give a tiny helper access to the active run
directory without passing it as an argument.

Separately, every script in the codebase needs a CLI: which CSV to read,
which embedding backend, whether to keep colleague-added pivot rows.
`argparse` is the standard library answer, and `parse_args` in
`option2_pipeline.py` shows every flag pattern you'll ever need.

This lesson walks through decorators, closures, and `argparse` end-to-end.

## What a decorator is

A decorator is a function that wraps another function. The `@name`
syntax above a function definition is sugar for "pass me through this
wrapper." When you write:

```python
@st.cache_data(show_spinner=False)
def list_csvs(run_dir_str: str) -> list[str]:
    return sorted(p.name for p in Path(run_dir_str).glob("*.csv"))
```

[`scripts/dashboard/lib.py:145-167`](../../scripts/dashboard/lib.py)

Python evaluates `st.cache_data(show_spinner=False)` first — that returns
a decorator function. Then `list_csvs` is defined. Then the decorator
wraps `list_csvs`, replacing the name `list_csvs` in the module
namespace with the wrapped version. From the outside, `list_csvs(...)`
is still callable; under the hood, the wrapper checks a cache before
calling the original function.

You can write your own decorators — they're just functions that take a
function and return a function. The codebase doesn't define custom ones,
but it consumes Streamlit's heavily.

## `@st.cache_data`: cache values

Use `@st.cache_data` when the function returns a *value* — a DataFrame, a
list, a dict, an int. Streamlit hashes the argument values, looks up the
result in a session-scoped store, and returns the cached value on
subsequent calls with the same arguments. If anything in the cache key
changes, it recomputes.

Example: `list_csvs` enumerates `*.csv` files in a run directory. Once
per run, the answer is stable, but Streamlit reruns the page on every
click. The decorator memoises the answer:

```python
@st.cache_data(show_spinner=False)
def list_csvs(run_dir_str: str) -> list[str]:
    return sorted(p.name for p in Path(run_dir_str).glob("*.csv"))
```

[`scripts/dashboard/lib.py:145-167`](../../scripts/dashboard/lib.py)

Two things to notice.

The argument is a *string*, not a `Path`. Streamlit's cache key has to
be hashable, and while `Path` objects technically are, stringifying them
makes the cache key obvious in the Streamlit UI's diagnostics view.
The function reconstructs a `Path` internally.

`show_spinner=False` suppresses the "Running list_csvs..." overlay.
Default is `True`, which is useful for slow operations but distracting
for cheap ones.

The cache key is the function name plus the argument values. So
`list_csvs("path/A")` and `list_csvs("path/B")` get *separate* cache
entries — switching runs does not stale-cache.

The dashboard uses `@st.cache_data` on every CSV/JSON loader:
`load_csv`, `load_json`, `list_csvs`, `list_other_files`, all sharing
the same shape.

## `@st.cache_resource`: cache handles

The other flavour, `@st.cache_resource`, is for things that *must not*
be copied: database connections, ML model instances, network clients.
Multiple sessions across multiple browser tabs share the *same* object
instance, never a copy.

The DuckDB connection in `Find a Ticket` uses it:

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

[`scripts/dashboard/pages/07_Find_a_Ticket.py:100-126`](../../scripts/dashboard/pages/07_Find_a_Ticket.py)

The accompanying teaching comment makes the distinction clear:

> `cache_resource` is for things that must not be copied across sessions
> — database connections, model instances. `cache_data` is for
> immutable values: DataFrames, lists, dicts. We mark `get_con` with
> `cache_resource` (the connection is a long-lived handle) and
> `distinct` with `cache_data` (the result is a list of strings).

[`scripts/dashboard/pages/07_Find_a_Ticket.py:10-16`](../../scripts/dashboard/pages/07_Find_a_Ticket.py)

The rule of thumb:

- Returns a value (DataFrame, list, dict, int, str) → `@st.cache_data`.
- Returns a handle (connection, file pointer, model instance,
  long-lived client) → `@st.cache_resource`.

If you pick wrong, two failure modes await. Using `cache_data` on a
DuckDB connection causes Streamlit to try to deepcopy the connection —
which fails, often loudly. Using `cache_resource` on a DataFrame breaks
isolation: one user mutating the cached frame would mutate it for
everyone.

## Closures

A closure is a function that "captures" variables from its enclosing
scope. The dashboard's home page uses one to define a tiny file-finder
without passing `run_dir` as an argument:

```python
run_dir = run_picker()
if run_dir is None:
    st.stop()
st.session_state["run_dir"] = str(run_dir)


def _first_existing(*names: str):
    for n in names:
        df = maybe_load_csv(run_dir, n)
        if df is not None:
            return df
    return None
```

[`scripts/dashboard/app.py:86-122`](../../scripts/dashboard/app.py)

Two patterns at once.

The function takes `*names: str`. The asterisk means "variadic
positional arguments" — the caller can pass any number of strings, and
they arrive bundled in a tuple. So `_first_existing("a.csv", "b.csv")`
is one call with `names = ("a.csv", "b.csv")`.

Inside the function, `run_dir` is referenced but never defined. Where
does it come from? Python's lookup rule: local scope, then enclosing
scope, then global, then builtins. `run_dir` is in the module-level
scope where `_first_existing` was defined, so the function captures it
as a free variable.

The wrapping comment in `app.py` calls this out explicitly:

> This is a *closure*: it has no `run_dir` parameter, but uses the
> `run_dir` variable from the enclosing module scope.

[`scripts/dashboard/app.py:111-114`](../../scripts/dashboard/app.py)

Why bother? Because the alternative is uglier. Without the closure, the
caller would write:

```python
extractions = first_existing(run_dir, "ollama_gemma3-4b_extractions.csv", "llm_extractions.csv")
backlog = first_existing(run_dir, "refined_opportunity_backlog.csv", "opportunity_backlog.csv")
```

Repeating `run_dir` six times. With the closure, it captures once:

```python
extractions = _first_existing("ollama_gemma3-4b_extractions.csv", "llm_extractions.csv")
backlog = _first_existing("refined_opportunity_backlog.csv", "opportunity_backlog.csv")
```

Closures are the natural fit for "tiny helper used a few lines below
that needs context the surrounding script already has." Don't reach for
them across modules — that defeats the readability win.

The dashboard library file uses closures inside `attach_friendly_titles`
to pass a lookup dict into `df.apply` without making it global:

```python
def attach_friendly_titles(df, human_labels, ...):
    out = df.copy()

    def title_for(row: pd.Series) -> str:
        try:
            wid = int(row.get(want_id_col))
        except (TypeError, ValueError):
            wid = None
        if wid is not None and wid in human_labels and human_labels[wid].get("title"):
            return human_labels[wid]["title"]
        return friendly_want_title(row.get(want_label_col, ""), row.get(top_jobs_col, ""))
    ...
```

[`scripts/dashboard/lib.py:761-820`](../../scripts/dashboard/lib.py)

`title_for` captures `human_labels`, `want_id_col`, `want_label_col`,
and `top_jobs_col` from the enclosing function. When passed to
`out.apply(title_for, axis=1)`, pandas calls it once per row with just
the row — and `title_for` already knows the lookup dict and column
names. No globals, no extra arguments.

## `argparse`: end-to-end CLI

Every script in the codebase exposes a CLI through `argparse`, the
standard library's command-line parser. The pattern is always: define a
`parse_args` function that returns a `Namespace`, then call it from
`__main__`.

The pipeline's `parse_args` shows every common option type:

```python
def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Option 2 data-science/NLP analysis on support ticket CSV.")
    parser.add_argument("--input", default="data_2may.csv", help="Path to source CSV")
    parser.add_argument("--output-dir", default="outputs", help="Directory for analysis outputs")
    parser.add_argument(
        "--embedding-backend",
        choices=["tfidf", "local", "openai"],
        default="tfidf",
        help="tfidf is fully local/no model download; local uses sentence-transformers; openai uses OPENAI_API_KEY.",
    )
    parser.add_argument(
        "--embedding-model",
        default="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        help="Local sentence-transformers model or OpenAI embedding model name.",
    )
    parser.add_argument(
        "--keep-summary-rows",
        action="store_true",
        help=(
            "Keep rows that have no Question text and no UID. "
            "By default these colleague-added empty/aggregation rows are dropped."
        ),
    )
    parser.add_argument(
        "--keep-pivot-columns",
        action="store_true",
        help=(
            "Keep colleague-added Google-Sheets pivot/cohort columns "
            "(Role/SVIP cohort dates, Russian Статус used as a count column). "
            "By default these are dropped at ingest."
        ),
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    run(parse_args(sys.argv[1:]))
```

[`scripts/option2_pipeline.py:1957-2019`](../../scripts/option2_pipeline.py)

Walk through it.

`argparse.ArgumentParser(description=...)` is the parser object. The
description shows up in `--help`.

`add_argument("--input", default="data_2may.csv", help=...)` declares
one flag. The pattern is `--name`. Argparse converts dashes in the name
to underscores in the resulting namespace, so `--output-dir` becomes
`args.output_dir`. The `default=` value is used when the flag is
omitted. The `help=` string is shown under `--help`.

`choices=["tfidf", "local", "openai"]` does input validation for free.
If the user passes `--embedding-backend invalid`, argparse rejects it
with a friendly "invalid choice: 'invalid' (choose from 'tfidf',
'local', 'openai')" error before the script body runs.

`action="store_true"` is the boolean-flag shortcut. The flag takes no
value. Present means `True`, absent means `False`. So `--keep-summary-
rows` on the command line gives you `args.keep_summary_rows == True`.
The opposite `action="store_false"` exists too.

`return parser.parse_args(argv)` does the actual parsing. Notice that
`parse_args` accepts `argv` as a parameter rather than reading
`sys.argv` internally. The teaching comment explains why:

> Taking `argv` as a parameter (rather than reading `sys.argv`
> internally) makes the function testable: a unit test can call
> `parse_args(["--input", "x.csv"])` directly.

[`scripts/option2_pipeline.py:1977-1979`](../../scripts/option2_pipeline.py)

The result is an `argparse.Namespace`, a tiny object whose attributes
are the parsed flags. `args.input` is the path. `args.embedding_backend`
is the backend name. `args.keep_summary_rows` is the boolean.

The bottom of the file ties it all together:

```python
if __name__ == "__main__":
    run(parse_args(sys.argv[1:]))
```

`sys.argv` is the list of command-line tokens, with `sys.argv[0]` the
script name and the rest the user's arguments. Slicing `[1:]` drops
the script name. Then `parse_args` returns a namespace, which `run`
consumes.

## Positional arguments vs flags

You'll see two argument styles in the wild.

A *flag* (also called an "optional argument") is prefixed with `--`:
`--input data.csv`, `--keep-summary-rows`. The user must name it.
Order doesn't matter.

A *positional argument* has no prefix: the user just types the value.
Order *does* matter. Positionals are how `cp source.txt dest.txt` works.

Argparse declares positionals the same way, just without the `--`:

```python
parser.add_argument("input_path", help="Path to the source CSV")
```

The pipeline uses only flags. Why? Because every parameter has a
sensible default and you want the user to opt into changes by name, not
by remembering the order. For a pipeline with seven parameters that
trade-off makes sense. For a tiny utility that takes exactly one path,
a positional is shorter.

## Common argparse patterns

A few more you'll encounter:

`type=int` coerces the parsed string to an integer. Without it, argparse
gives you `"5"` as a string and you have to convert.

```python
parser.add_argument("--n-subtopics", type=int, default=None, help="Override the auto-chosen k.")
```

`nargs="+"` accepts one or more values. Useful for "list of files"
arguments.

`required=True` on a flag makes it mandatory. Argparse exits with an
error if the flag is missing.

`metavar="FILE"` controls how the argument appears in help text. By
default the metavar is the dash-cased name; you can override it for
clarity.

For end-to-end documentation of every pattern, run `python
your_script.py --help`. Argparse generates the help text automatically
from your `add_argument` calls — another reason to write descriptive
`help=` strings.

## Putting it together

Decorators wrap functions to add behaviour without modifying the body.
The dashboard uses Streamlit's two cache decorators almost exclusively.
Closures let small inner functions share context with their surrounding
scope without parameter plumbing — used in the home page's
`_first_existing` and the lib's `attach_friendly_titles`.

`argparse` is the standard library's CLI parser. The pattern is always:
define `parse_args` returning a `Namespace`, call it from `__main__`,
read attributes off the namespace inside `run`. The pipeline's
`parse_args` shows every flag style you need: defaults, `choices`,
`action="store_true"`.

These three together — caching, closures, CLI — are the difference
between a script that works on your laptop and a script that survives
production reruns.

## Try it

From the repo root, write a small CLI that lists CSV files in the
latest run directory, optionally filtered by a pattern, with a `--limit`
flag controlling how many to show. Use `argparse` and apply the same
patterns as `parse_args` in the pipeline:

```bash
.venv/bin/python -c "
import argparse, sys
from pathlib import Path

def parse_args(argv):
    p = argparse.ArgumentParser(description='List CSVs in the latest run.')
    p.add_argument('--outputs-dir', default='outputs')
    p.add_argument('--pattern', default='*.csv')
    p.add_argument('--limit', type=int, default=10)
    p.add_argument('--show-sizes', action='store_true')
    return p.parse_args(argv)

def run(args):
    runs = sorted(p for p in Path(args.outputs_dir).glob('option2_*') if p.is_dir())
    run_dir = runs[-1]
    files = sorted(run_dir.glob(args.pattern))[: args.limit]
    for f in files:
        if args.show_sizes:
            print(f'{f.name:<45} {f.stat().st_size:>10}')
        else:
            print(f.name)

run(parse_args(sys.argv[1:]))
" --pattern '*assignments*' --show-sizes --limit 5
```

Then invoke it with `--help` (you'll need to put the code in a real
file for that to render cleanly) and confirm argparse generates the
expected help text from your `add_argument` calls. Add a `choices=`
constraint on `--pattern` and watch argparse reject invalid values.
