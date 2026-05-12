# Error Handling and Soft Fail

## The problem

The pipeline imports UMAP, HDBSCAN, statsmodels, NetworkX, plotly,
matplotlib, seaborn, and DuckDB. Half of those have C-extension
dependencies that fail to install on locked-down corporate laptops. If any
import fails at the top of the file, the whole pipeline dies — even though
60% of its work doesn't need that library at all.

The dashboard reads CSVs that may be empty, missing, malformed, or have
NaN cells. If `int("")` raises `ValueError` and you don't catch it, the
page crashes for the user.

The LLM extractor calls a local Ollama server over HTTP. If the server
isn't running, the underlying `URLError` looks like
`<urlopen error [Errno 61] Connection refused>` to the user, which is
useless.

In each case, the right answer is to fail *softly*: skip the optional
stage, return a sentinel, or wrap the obscure exception in a friendlier
one. This lesson walks the four soft-fail patterns the codebase uses.

## `try/except` and the `safe_int` / `safe_float` helpers

The simplest soft-fail is wrapping a coercion in `try/except`:

```python
def safe_int(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def safe_float(value: Any, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback
```

[`scripts/dashboard/lib.py:467-510`](../../scripts/dashboard/lib.py)

Three things to notice.

The `except` clause takes a tuple of exception types: `(TypeError,
ValueError)`. `int(None)` raises `TypeError`. `int("")` raises
`ValueError`. Catching both lets one helper handle all the dirty cells
real CSVs produce — empty strings, `None`, the literal text `"NaN"`, the
string `"true"`.

The fallback is a parameter, not a hard-coded zero. Callers who care can
override it: `safe_int(row.get("count"), fallback=-1)` to distinguish
"missing" from "zero."

The functions are tiny. That is the point. You don't need a 30-line
defensive coercion utility — you need a four-line one used everywhere.
The dashboard's KPI row uses `safe_int` to read JSON fields:

```python
candidates_target = safe_int(status_data.get("candidates"), fallback=0)
```

[`scripts/dashboard/pages/01_Extraction_Progress.py:108`](../../scripts/dashboard/pages/01_Extraction_Progress.py)

That single line absorbs every shape of "this key might be missing,
might be a string, might be `None`, might be a float."

This is the *EAFP* style — "Easier to Ask Forgiveness than Permission."
The Pythonic alternative to `if isinstance(value, int): ... else: ...`
chains.

## `raise X from exc`: exception chaining

When you wrap a low-level exception in a friendlier one, you should
preserve the original cause. The `from` keyword is how:

```python
try:
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = json.loads(response.read().decode("utf-8"))
except urllib.error.URLError as exc:
    raise RuntimeError(
        f"Could not reach Ollama at {ollama_url}. Is it running? ({exc})"
    ) from exc
```

[`scripts/label_user_wants.py:159-165`](../../scripts/label_user_wants.py)

The `from exc` clause attaches the original exception as `__cause__` on
the new one. When Python prints the traceback, the user sees both:

```
urllib.error.URLError: <urlopen error [Errno 61] Connection refused>

The above exception was the direct cause of the following exception:

RuntimeError: Could not reach Ollama at http://localhost:11434. Is it running? (...)
```

The friendly message is on top. The technical detail is preserved
underneath. Without `from exc`, Python would say "During handling of the
above exception, another exception occurred" — semantically different
and more confusing.

The same pattern shows up in `llm_extract_rich_tickets.py`:

```python
raise RuntimeError(f"Ollama request failed. Is Ollama running at {ollama_url}? {exc}") from exc
```

[`scripts/llm_extract_rich_tickets.py:696`](../../scripts/llm_extract_rich_tickets.py)

Use `from exc` whenever you re-raise. The only time to use `from None`
is when the original exception is genuinely irrelevant and would confuse
the reader.

## Soft-fail imports: `optional_import`

The pipeline's signature soft-fail pattern is here:

```python
def optional_import(module_name: str) -> Any | None:
    try:
        return __import__(module_name)
    except Exception:
        return None
```

[`scripts/option2_pipeline.py:193-221`](../../scripts/option2_pipeline.py)

Three teaching points.

`__import__` is the low-level builtin behind the `import` statement. It
takes a string (so the module name can be computed at runtime) and
returns the module object on success. You can then assign the result to
a local variable and use it like any normal import.

The `except Exception` is intentionally broad. Why not just
`except ImportError`? Because some libraries (HDBSCAN with mismatched
NumPy ABI versions, OpenMP-linked builds on macOS) raise `RuntimeError`
or `OSError` *during* import, not `ImportError`. Catching the broad base
class covers all the failure modes the operator might hit.

The return type `Any | None` is a PEP 604 union — the new spelling of
`Optional[Any]`. (Lesson 6 covers this in detail.)

A caller uses the result with a truthiness check:

```python
plt = optional_import("matplotlib.pyplot")
if plt is None:
    print("[warn] matplotlib not installed; skipping charts.", file=sys.stderr)
    return
```

The pattern is mentioned at
[`scripts/option2_pipeline.py:1549`](../../scripts/option2_pipeline.py),
where the comments call out: "same pattern as `optional_import` — if
matplotlib or seaborn is missing, skip the stage."

## Lazy imports inside functions

Some libraries are expensive to import even when they work. UMAP loads
NumPy, scipy, llvmlite, and numba — easily two seconds at module-load
time. If your pipeline only uses UMAP in one stage, importing it at the
top of the file slows down every other stage too.

The fix is to move the import *inside* the function:

```python
try:
    import umap

    n_neighbors = min(30, max(5, len(work) // 200))
    reducer_2d = umap.UMAP(n_components=2, n_neighbors=n_neighbors, min_dist=0.08, metric="cosine", random_state=42)
    coords = reducer_2d.fit_transform(dense)
    x, y = coords[:, 0], coords[:, 1]
    reducer_cluster = umap.UMAP(n_components=10, n_neighbors=n_neighbors, min_dist=0.0, metric="cosine", random_state=42)
    reduced = reducer_cluster.fit_transform(dense)
except Exception as exc:
    print(f"[warn] UMAP unavailable/failed: {exc}. Clustering on SVD/embedding space.", file=sys.stderr)

try:
    import hdbscan

    min_cluster_size = max(12, min(80, len(work) // 90))
    clusterer = hdbscan.HDBSCAN(min_cluster_size=min_cluster_size, min_samples=max(5, min_cluster_size // 3), metric="euclidean")
    labels = clusterer.fit_predict(reduced)
    probabilities = getattr(clusterer, "probabilities_", np.ones(len(work)))
except Exception as exc:
    print(f"[warn] HDBSCAN unavailable/failed: {exc}. Falling back to MiniBatchKMeans.", file=sys.stderr)
    from sklearn.cluster import MiniBatchKMeans

    k = max(8, min(35, int(math.sqrt(len(work) / 2))))
    clusterer = MiniBatchKMeans(n_clusters=k, random_state=42, n_init=20, batch_size=1024)
    labels = clusterer.fit_predict(reduced)
    probabilities = np.ones(len(work))
```

[`scripts/option2_pipeline.py:1347-1373`](../../scripts/option2_pipeline.py)

This is `cluster_texts`. Three patterns combined.

The import is inside the `try` block. If `import umap` fails — wrong
Python version, missing libomp, broken numba — the `except Exception`
catches it, logs a warning to stderr, and continues with whatever
`reduced` was before (just the SVD output). Other stages that don't need
UMAP never pay the import cost.

The HDBSCAN block does the same, but its `except` includes a *fallback
import* of `MiniBatchKMeans`. Sklearn is a hard dependency anyway, so
this import is guaranteed to succeed. The fallback gives every ticket a
cluster label even when the preferred algorithm fails.

`getattr(clusterer, "probabilities_", np.ones(len(work)))` is yet
another defensive idiom — it returns the attribute if it exists or the
fallback otherwise. Older HDBSCAN versions didn't expose
`probabilities_`. `getattr` with a default is the safe lookup.

## `st.stop()`: the Streamlit early exit

Streamlit pages are scripts that run top to bottom on every interaction.
If a page can't proceed — no run directory selected, the required CSV is
missing, the user hasn't filled in a required field — you don't want the
script to keep going and crash on the next line.

The home page does this on the very first useful action:

```python
run_dir = run_picker()
if run_dir is None:
    st.stop()
st.session_state["run_dir"] = str(run_dir)
```

[`scripts/dashboard/app.py:86-89`](../../scripts/dashboard/app.py)

`st.stop()` raises a `StopException` internally that Streamlit catches
silently. The page renders whatever it has so far (here, just the title
and the empty sidebar message) and stops. No error, no exception
visible to the user, no half-rendered page.

Every page in the dashboard does this. The Extraction Progress page:

```python
candidates = list(run_dir.glob("*extractions.jsonl"))
if not candidates:
    st.info(
        "No extraction logs in this run yet. "
        "When an extraction starts, this page will fill in automatically."
    )
    st.stop()
```

[`scripts/dashboard/pages/01_Extraction_Progress.py:94-100`](../../scripts/dashboard/pages/01_Extraction_Progress.py)

The pattern is always: render an explanation (`st.info`, `st.warning`,
`st.error`), then `st.stop()`. The user sees a calm, useful message
instead of a Python traceback.

## Combining the patterns: the `humanize_desire` example

The dashboard's `humanize_desire` puts three of these patterns in one
small function:

```python
def humanize_desire(value: str) -> str:
    if not isinstance(value, str):
        return ""
    return DESIRE_LABELS.get(value.strip(), value.replace("_", " ").capitalize())
```

[`scripts/dashboard/lib.py:563-586`](../../scripts/dashboard/lib.py)

The `isinstance` guard handles the `None` / `NaN` / non-string case
without exception machinery. The `dict.get(key, default)` call is its own
soft-fail: missing keys produce the title-cased fallback, never a
`KeyError`. No `try/except` is needed because each step uses methods
that already provide a graceful default path.

That is the lesson on when *not* to use exceptions: when you can express
the missing case with `isinstance`, `is None`, `dict.get(default)`, or
`getattr(obj, name, default)`, those are cheaper and clearer than
`try/except`. Save `try/except` for cases where the failure is genuinely
exceptional or the API only signals failure by raising.

## When to catch broadly vs narrowly

You will see both styles in this codebase.

`safe_int` catches a precise tuple `(TypeError, ValueError)`. It knows
exactly which exceptions `int(value)` can raise and handles them
specifically. That is the correct default.

`optional_import` and `cluster_texts` catch the bare `Exception`. The
comment in `optional_import` explains why: import-time failures from
binary-incompatible C extensions can be `RuntimeError`, `OSError`,
`ImportError`, or even subtle ABI panics. Listing them all is brittle —
the next library update will add a new failure mode. Catching `Exception`
is the right call when you genuinely don't care *why* it failed, only
that the optional feature isn't available.

`load_json` does the same:

```python
try:
    return json.loads(path.read_text(encoding="utf-8"))
except Exception:
    return None
```

[`scripts/dashboard/lib.py:255-281`](../../scripts/dashboard/lib.py)

A corrupt sidecar JSON file should not crash the dashboard. Catching
broadly and returning `None` lets the page proceed; the caller sees
"file missing" and degrades gracefully.

The rule of thumb:

- Catch the narrowest set of exception types you can name when the
  failure mode is well-understood and the recovery is specific.
- Catch `Exception` (never bare `except:`) when the failure surface is
  genuinely diverse and recovery is the same in every case: log,
  return a sentinel, continue.

Bare `except:` (without any class) is wrong. It catches
`KeyboardInterrupt` and `SystemExit` too, making the program impossible
to abort. The codebase never uses it.

## Try it

From the repo root, write a script that loads `manager_summary.csv` from
the latest run and computes a "rank score" — the manager's tickets
divided by their average context-depth score — wrapping each cell read
in `safe_int` / `safe_float` so dirty values don't crash the loop:

```bash
.venv/bin/python -c "
import sys
sys.path.insert(0, 'scripts/dashboard')
from lib import safe_int, safe_float
from pathlib import Path
import pandas as pd
runs = sorted(p for p in Path('outputs').glob('option2_*') if p.is_dir())
run = runs[-1]
df = pd.read_csv(run / 'manager_summary.csv')
for _, row in df.head(10).iterrows():
    tickets = safe_int(row.get('tickets'))
    score = safe_float(row.get('avg_context_score'))
    if score == 0:
        continue
    rank = tickets / score
    print(f'{str(row.get(\"manager\", \"\"))[:25]:<25}  rank={rank:7.1f}')
"
```

Then deliberately corrupt one row's `tickets` cell (overwrite it with the
string `'NaN'` or `''` in a copy of the CSV) and confirm the script
still runs without crashing — the bad row gets `tickets=0` and is
skipped by the `if score == 0: continue` guard.
