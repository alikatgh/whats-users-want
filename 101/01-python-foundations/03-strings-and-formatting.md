# Strings and Formatting

## The problem

You are rendering `len(enriched):,` tickets, a percentage, and a money
risk score on a Streamlit KPI card. The number is `6728`. You want to see
`"6,728"`, not `"6728"`. The percentage is `0.413`. You want
`"41.3%"`, not `"0.413"`. The money risk is `2.7173913…`. You want
`"2.72"`. And before any of that, the raw text from the CSV needs its
`\r\n` line endings normalised, its tabs collapsed to spaces, and its
trailing whitespace stripped, because every later step assumes a clean
string.

Strings flow through this pipeline in two directions: dirty input gets
cleaned on the way in, and clean numbers get formatted on the way out. The
patterns repeat across every script. This lesson shows the small set of
idioms that cover both directions.

## f-strings: the format-spec mini-language

You will not see `"%s" % value` or `str.format(...)` anywhere in this
codebase. Every formatted string is an f-string.

Inside `{...}` you can attach a colon followed by a format specifier. Three
specifiers cover 90% of the dashboard's display logic.

`{count:,}` inserts a thousands separator. The home page uses it on every
KPI:

```python
c1.metric(
    "Tickets analyzed",
    f"{len(enriched):,}" if enriched is not None else "—",
)
```

[`scripts/dashboard/app.py:134-137`](../../scripts/dashboard/app.py)

`{x:.2f}` rounds a float to two decimals. The Manager page uses it for
average context scores:

```python
c1.metric("Top manager (avg score)", top_manager["manager"], f"{top_manager['avg_context_score']:.2f}")
```

[`scripts/dashboard/pages/04_Manager_Note_Quality.py:123`](../../scripts/dashboard/pages/04_Manager_Note_Quality.py)

`{x*100:.1f}%` is the percentage idiom. The expression inside `{...}` is
arbitrary Python, so multiplication happens first and `:.1f` formats the
result. The Extraction Progress page uses it for the progress bar text:

```python
st.progress(pct, text=f"{completed:,} of {candidates_target:,} ({pct*100:.1f}%)")
```

[`scripts/dashboard/pages/01_Extraction_Progress.py:139`](../../scripts/dashboard/pages/01_Extraction_Progress.py)

A subtler one — `f"{pct:.1%}"` — is mentioned in the pipeline's teaching
comments at
[`scripts/option2_pipeline.py:1642`](../../scripts/option2_pipeline.py): the
`%` format spec multiplies by 100 *and* appends the percent sign in one
step. Both forms produce the same output; the explicit `*100:.1f%` is
slightly more transparent and is what most of the pages use.

Format specs you will also encounter in this code:

- `{wid:>3}` — right-align in a 3-char field. Used in
  [`scripts/label_user_wants.py:397`](../../scripts/label_user_wants.py) so
  cluster IDs line up in the CLI log.
- `{status:<10}` — left-align in a 10-char field. Same line. Together they
  produce a column-aligned status line: `cluster   3  status=ok`.

The mini-language is documented in PEP 3101. You only need a handful of
specifiers in practice.

## `clean_text`: stripping CRLF, tabs, and edges

The first line of defence on incoming CSV text is `clean_text` in the
pipeline:

```python
def clean_text(value: Any) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()
```

[`scripts/option2_pipeline.py:243-274`](../../scripts/option2_pipeline.py)

Three string operations chain here.

`str.replace(old, new)` returns a new string with every occurrence of `old`
replaced by `new`. Strings are immutable in Python, so `replace` does not
mutate `text`; it returns a new string and you reassign. Order matters:
`"\r\n"` is replaced first so the trailing CR doesn't leak through to the
second pass.

`re.sub(r"[ \t]+", " ", text)` collapses runs of spaces and tabs into a
single space. Crucially, `\n` is not in the character class, so newlines
survive. That's deliberate: `featurize_tickets` later counts non-empty
lines as a forensic signal, so the line structure must be preserved.

`text.strip()` removes leading and trailing whitespace (spaces, tabs,
newlines). Use it whenever you receive text from a CSV — exporters love
to leave trailing spaces.

You can pass arguments to `strip` to remove specific characters:
`text.strip("_")` strips leading and trailing underscores, useful for
cleaning up cluster labels like `"_recover_access_"`.

## `normalize_space`: a single-line variant

The companion function flattens *every* whitespace run, including
newlines:

```python
def normalize_space(value: Any) -> str:
    return re.sub(r"\s+", " ", clean_text(value)).strip()
```

[`scripts/option2_pipeline.py:277-296`](../../scripts/option2_pipeline.py)

`\s` matches *all* whitespace (space, tab, CR, LF, form-feed). The pattern
`\s+` collapses any consecutive whitespace into one space. The function
calls `clean_text` first so it inherits the NaN/None safety, then applies
the more aggressive flattening.

The two functions express a deliberate distinction:

- `clean_text` — preserve line structure, normalise everything else. For
  the `Question` column, where line count is meaningful.
- `normalize_space` — flatten to one line. For UIDs, manager names,
  category labels, the `question_flat` field used for word counting.

## `.lower()`, `.upper()`, `.split()`, `.join()`

The taxonomy builder uses the lowercase + tokenise + join chain repeatedly.
A simplified slice from `label_cluster`:

```python
for token in re.findall(r"[A-Za-z][A-Za-z\-']{2,}", text.lower()):
    if token in STOPWORDS or len(token) <= 3:
        continue
    tokens[token] += 1
top = [tok for tok, _ in tokens.most_common(top_n)]
return "_".join(top) if top else "misc"
```

[`scripts/build_user_wants_taxonomy.py:430-437`](../../scripts/build_user_wants_taxonomy.py)

`text.lower()` returns a lowercased copy. Always use it before string
comparisons or stopword checks — `"Ban" in {"ban"}` is `False`,
`"Ban".lower() in {"ban"}` is `True`.

`"_".join(top)` is the inverse of `split`: it joins an iterable of strings
with a separator. The result is `"recover_access_unblocked_dealer"` style
labels.

`text.split(sep)` is the partner. The dashboard's `_top_job` uses it twice:

```python
def _top_job(top_jobs: str) -> str:
    if not isinstance(top_jobs, str) or not top_jobs.strip():
        return "other"
    first = top_jobs.split(",")[0].strip()
    return first.split(":")[0].strip() or "other"
```

[`scripts/dashboard/lib.py:626-650`](../../scripts/dashboard/lib.py)

Splitting on `","`, taking `[0]`, splitting again on `":"`. That is how
you parse a tiny ad-hoc format like `"recover_access:29, fix:2"` into
`"recover_access"`. Each step strips the result so leading or trailing
spaces from the source string don't poison the value.

## The truncation idiom

Long ticket text needs to be shortened to fit Excel cells, prompt
budgets, and table cells. Two scripts use the same idiom:

```python
def compact(text: str, max_len: int = 520) -> str:
    text = re.sub(r"\s+", " ", str(text)).strip()
    return text if len(text) <= max_len else text[: max_len - 3].rstrip() + "..."
```

[`scripts/split_outlier_bucket.py:87-117`](../../scripts/split_outlier_bucket.py)

And the LLM-labeller's `clamp`:

```python
def clamp(text: str, n: int) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(text) <= n:
        return text
    return text[: n - 3].rstrip() + "..."
```

[`scripts/label_user_wants.py:61-93`](../../scripts/label_user_wants.py)

The pattern: `text[: n - 3].rstrip() + "..."`.

`text[: n - 3]` is a slice. Slicing a string with `[:k]` returns the
first `k` characters. `n - 3` reserves three characters for the ellipsis,
so the final string is exactly `n` characters long.

`.rstrip()` strips trailing whitespace from the slice. If you cut mid-word
or mid-space, you get something like `"User wants to "` with a trailing
space; rstrip removes it before you append the ellipsis.

`+ "..."` appends three literal dots. Three ASCII dots, not the single
character `"…"` (U+2026), because some downstream sinks (CSV readers,
Excel) handle ASCII more reliably.

A subtler detail: `str(text or "")`. The `or ""` guards against `None`.
`None or ""` evaluates to `""`. `"foo" or ""` evaluates to `"foo"`. This
is the standard Pythonic way to coerce a possibly-`None` value to a string
without writing a conditional.

## `repr()` in CLI logs

When the pipeline drops noise columns, it logs which ones were dropped:

```python
print(
    f"[info] Dropped {len(dropped_cols)} colleague pivot/cohort columns: "
    + ", ".join(repr(c) for c in dropped_cols),
    file=sys.stderr,
)
```

[`scripts/option2_pipeline.py:1882-1886`](../../scripts/option2_pipeline.py)

`repr(value)` returns the *programmer-facing* string representation. For a
plain string it adds quotes. So `"Role\n📆: 2026-04-06"` formatted with
`str()` would print as a real two-line block in your terminal — confusing.
With `repr()` it becomes `'Role\n📆: 2026-04-06'`, all on one line, with
the newline visible as `\n`.

When you log values that might contain whitespace, control characters, or
non-ASCII, use `repr` so the log stays parseable. When you want to display
the value to an end user, use `str` (or no conversion at all in an
f-string).

## Why this matters

Strings are how the pipeline talks to the user, the disk, and the next
stage of itself. The codebase uses about a dozen distinct string idioms
(f-string `:,`, `:.2f`, `:.1%`, `replace`, `strip`, `lower`, `split`,
`join`, `re.sub` for whitespace, `text[: n-3] + "..."`, `repr` for
logs, `str(x or "")` for None safety) and they appear hundreds of times.
Recognising them on sight is the difference between reading the code and
parsing it.

## Try it

From the repo root, write a small script that takes a path to a run
directory and prints each manager's average context-depth score formatted
as a percentage with one decimal:

```bash
.venv/bin/python -c "
import sys, pandas as pd
from pathlib import Path
runs = sorted(p for p in Path('outputs').glob('option2_*') if p.is_dir())
run = runs[-1]
df = pd.read_csv(run / 'manager_summary.csv')
for _, row in df.head(10).iterrows():
    name = str(row['manager'] or '').strip()
    score = row.get('avg_context_score', 0)
    n = int(row.get('tickets', 0))
    print(f'{name[:30]:<30}  {score:.2f}   tickets={n:,}')
"
```

Now add an ellipsis truncation: any name longer than 30 characters should
be cut to 30 with the `text[: n-3].rstrip() + "..."` idiom (replacing the
`name[:30]` slice). Run it and confirm the alignment still works.
