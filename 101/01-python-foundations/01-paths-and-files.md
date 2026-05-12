# Paths and Files

## The problem

You have a script that lives at `scripts/dashboard/lib.py`. It needs to find a
sibling directory at `outputs/option2_*/` no matter where the user runs it
from — from the repo root, from `scripts/`, from a Streamlit subprocess
launched in a different working directory. It also needs to enumerate every
matching subdirectory, sort them by timestamp, check which ones are real
folders (not stray zip files), and read their sizes.

Strings cannot do this cleanly. `os.path.join`, `os.listdir`, and string
concatenation get you there but leave you splicing platform-specific
separators by hand. `pathlib.Path` was added in Python 3.4 to retire that
whole vocabulary. Every script in this codebase uses it. This lesson walks
through the four idioms you'll see most often.

## Anchoring the project root

Look at the top of `scripts/dashboard/lib.py`:

```python
PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
```

That is two lines, and the first one is doing four things. Walk it left to
right. [`scripts/dashboard/lib.py:56-60`](../../scripts/dashboard/lib.py)

`__file__` is the dunder variable Python sets to the path of the currently
executing module — typically a relative path like
`"scripts/dashboard/lib.py"` or whatever the caller imported it as.

`Path(__file__)` wraps that string in a `Path` object so the next operations
get the rich pathlib API instead of bare-string manipulation.

`.resolve()` turns whatever the path was — relative, containing `..`,
containing symlinks — into a single absolute, canonical filesystem path.
After this call the path is unambiguous on every platform.

`.parents` is a tuple-like sequence of every ancestor directory.
`parents[0]` is the immediate parent, `parents[1]` is the grandparent, and so
on. The file is at `scripts/dashboard/lib.py`, so `parents[0]` is
`scripts/dashboard`, `parents[1]` is `scripts`, and `parents[2]` is the
project root. Counting parents is brittle if you move the file, so this
expression is a contract: "this file lives two levels under the project
root."

The result, `PROJECT_ROOT`, is a `Path` you can keep using. The next line —

```python
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
```

— uses the `/` operator on `Path`. That is operator overloading: pathlib
defines `Path.__truediv__` so `path / "name"` returns a new `Path` joining
them with the host operating system's separator (`/` on macOS and Linux, `\`
on Windows). You never write the separator yourself.

The two lines together give every dashboard page a stable answer to "where
is this file?" and "where are the runs?" — without any of them touching
`os.path`.

## Globbing for run directories

The dashboard's `list_runs` function shows the second core pattern:

```python
def list_runs() -> list[Path]:
    runs = sorted(
        [p for p in OUTPUTS_DIR.glob("option2_*") if p.is_dir()],
        key=lambda p: p.name,
        reverse=True,
    )
    return runs
```

[`scripts/dashboard/lib.py:63-89`](../../scripts/dashboard/lib.py)

`OUTPUTS_DIR.glob("option2_*")` is the pathlib version of the shell's
`ls outputs/option2_*`. The `*` is a wildcard. It returns a generator of
matching `Path` objects — the function is lazy until you iterate it.

The list comprehension `[p for p in OUTPUTS_DIR.glob(...) if p.is_dir()]`
filters to actual directories. There might be a stray `.zip` archive, a
hidden `.DS_Store`, or a half-deleted file lying around — `is_dir()` weeds
those out cleanly. You will see `is_file()` used the same way elsewhere when
the goal is to skip directories.

`sorted(..., key=lambda p: p.name, reverse=True)` is the standard custom
sort. The key function pulls out the bare folder name (a string like
`"option2_20260415_142233"`). Reverse means newest first. The trick that
makes this work cheaply: the names embed a `YYYYMMDD_HHMMSS` timestamp, so
lexicographic sort and chronological sort agree. You do not need
`datetime.strptime` here — strings are enough.

If you ever need a recursive glob that walks subdirectories, switch to
`rglob("option2_*")` or `glob("**/option2_*")`. Plain `glob` does not
recurse.

## Existence and size

Pathlib gives you several "is this real?" checks. The dashboard uses them in
nearly every helper. Here is `file_size_bytes`:

```python
def file_size_bytes(path: Path) -> int:
    return path.stat().st_size if path.exists() else 0
```

[`scripts/dashboard/lib.py:370-385`](../../scripts/dashboard/lib.py)

Two methods on display. `path.exists()` is the cheap predicate — it returns
`True` if anything by that name is present, regardless of file type. It is
the safe pre-check before any operation that would otherwise raise
`FileNotFoundError`.

`path.stat()` returns an `os.stat_result`, the same struct the OS returns to
`stat(2)`. It contains `st_size` (bytes), `st_mtime` (modification time as a
Unix timestamp), `st_mode`, and so on. This is how the dashboard reports
file sizes and ages. You will see `stat().st_mtime` used in
`file_mtime` two functions above to power the "is the extraction still
running?" logic.

The pattern is always: `exists()` first, `stat()` second. If you skip the
existence check, `stat()` raises on missing files, and you have to wrap it
in `try/except FileNotFoundError`. The two-step idiom is shorter and
clearer.

## Operator overloading: `OUTPUTS_DIR / "option2_..."`

You have already seen `OUTPUTS_DIR / "outputs"`. The same operator works on
any `Path`. Inside `load_csv` the dashboard does:

```python
path = Path(run_dir_str) / name
if not path.exists():
    return pd.DataFrame()
return pd.read_csv(path)
```

[`scripts/dashboard/lib.py:204-225`](../../scripts/dashboard/lib.py)

`run_dir_str` is a string (Streamlit's cache requires hashable arguments,
and stringifying the path makes the cache key obvious). The first line wraps
it back into a `Path`, then `/` joins on a bare filename. The result is
ready to pass straight to `pd.read_csv` — pandas accepts `Path` objects
everywhere it accepts strings.

Notice what is *not* there: no `os.path.join`, no f-string concatenation,
no manual separator. The `/` operator does it.

## Creating directories: `ensure_dir`

The pipeline's writer-side equivalent lives in `option2_pipeline.py`:

```python
def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
```

[`scripts/option2_pipeline.py:224-240`](../../scripts/option2_pipeline.py)

This is the Pythonic `mkdir -p`. Two flags do the work.

`parents=True` creates intermediate directories as needed. If you pass
`outputs/option2_20260503_104500/charts` and only `outputs/` exists, both
missing levels are created in one call. Without this flag pathlib raises
`FileNotFoundError` when a parent is missing.

`exist_ok=True` suppresses the `FileExistsError` that would fire on the
second call. Idempotent setup: you can call `ensure_dir` ten times in a row
and only the first call does any work.

The function returns `None` (no `return` statement). That is conventional
for procedural side-effect functions — making things rather than computing
things. Every output directory in `outputs/option2_<stamp>/` springs into
existence on first use thanks to this helper.

## Reading metadata: `file_mtime` and the live monitor

The dashboard uses `stat()` again, this time for modification time, to
detect "is the extraction process still writing?":

```python
def file_mtime(path: Path) -> datetime | None:
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime)
```

[`scripts/dashboard/lib.py:346-367`](../../scripts/dashboard/lib.py)

`stat().st_mtime` returns a Unix timestamp — seconds since 1970-01-01
UTC, as a float. `datetime.fromtimestamp(...)` converts it to a localised
`datetime` so the dashboard can subtract it from "now" and compute "did
this file get touched in the last 90 seconds?" That is how the
Extraction Progress page decides between the "running now" and "idle"
status badges.

The pattern again: existence check first, `stat()` second. If you call
`stat()` on a missing file, you get `FileNotFoundError` — the
`exists()` guard is what keeps the function safe.

## When string paths still appear

Pathlib is the rule, but a few APIs at the edges of the project still
want strings.

Streamlit's caching is the loudest offender. The dashboard's `load_csv`
takes `run_dir_str: str` rather than `run_dir: Path`:

```python
@st.cache_data(show_spinner=False)
def load_csv(run_dir_str: str, name: str) -> pd.DataFrame:
    path = Path(run_dir_str) / name
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)
```

[`scripts/dashboard/lib.py:203-225`](../../scripts/dashboard/lib.py)

The reason is in the docstring: Streamlit's cache key has to be a
hashable value, and while `Path` objects technically are, stringifying
makes the key obvious in Streamlit's diagnostics view. The function
reconstructs a `Path` internally, then proceeds normally.

Same shape in `list_csvs`, `list_other_files`, `load_json`. The boundary
is a `str` for the cache; everything inside is `Path`. That is the
right discipline: convert at the edge, work with `Path` in the body.

DuckDB's `read_csv_auto`, sklearn's joblib loader, and a few other
third-party APIs also prefer strings. `str(path)` returns the platform's
canonical string form — `"outputs/option2_20260415"` on macOS and
Linux, `"outputs\\option2_20260415"` on Windows. Pathlib does the right
thing on each.

## Why pathlib over strings

Putting it together:

- `Path(__file__).resolve().parents[N]` gives you a stable anchor that
  survives `cd`, symlinks, and weird launchers.
- The `/` operator builds child paths without you ever typing a separator.
- `.glob("pattern")` enumerates matching paths lazily; combine with
  `is_dir()` / `is_file()` to filter.
- `.exists()` is the cheap predicate; `.stat()` is the metadata window;
  `.mkdir(parents=True, exist_ok=True)` is the creator.
- Methods chain naturally because every step returns either a `Path` or a
  scalar — there is no mixed string/object world.
- At the boundary with APIs that want strings (Streamlit's cache, some
  third-party libraries) call `str(path)`. Inside your own code, keep it
  a `Path`.

You can do all of this with the `os` module. You will end up writing more
code, with more conditionals for "did the platform use `/` or `\`," and
your call sites will be harder to read. The whole codebase made the
trade-off in the other direction, and the consistency pays off every time
you read someone else's helper for the first time.

## Try it

From the repo root, run this Python one-liner. It mirrors what
`list_runs()` does:

```bash
.venv/bin/python -c "
from pathlib import Path
project_root = Path('.').resolve()
outputs = project_root / 'outputs'
runs = sorted(
    [p for p in outputs.glob('option2_*') if p.is_dir()],
    key=lambda p: p.name,
    reverse=True,
)
for r in runs:
    enriched = r / 'enriched_tickets.csv'
    size_mb = enriched.stat().st_size / (1024 * 1024) if enriched.exists() else 0
    print(f'{r.name}  {size_mb:6.2f} MB')
"
```

You should see one line per run directory, with the size of its
`enriched_tickets.csv` if that file exists. If you have no runs yet, run
`scripts/option2_pipeline.py` first.

Then change the script: replace `Path('.')` with
`Path(__file__).resolve().parents[N]` style anchoring (you'll need to put
the code in a file under `scripts/` and pick the right `N`). Confirm it
still finds the same runs from any working directory.
