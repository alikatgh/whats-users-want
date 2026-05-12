# Collections and Comprehensions

## The problem

For each of the 10 user-want clusters you discovered, you need to find the
six most distinctive tokens in the cluster's text. You also need to count
how many of the top jobs in each cluster are `"recover_access"` versus
`"fix_product_flow"`. You need a fast way to test whether a phrase is in a
blacklist of "useless generic outputs the model loves to return." And you
need a stable mapping from machine codes (`"recover_access"`) to friendly
labels (`"Recover account access"`) that every page of the dashboard can
share.

These four jobs map directly onto Python's four core collection types:
`Counter` for frequency tables, `set` for fast membership tests, `dict`
for code-to-human mappings, and `list` (with comprehensions) for
filtered transformations. This lesson walks through each pattern as it
appears in the codebase.

## List comprehensions everywhere

A list comprehension is the syntax `[expression for item in iterable if
condition]`. It produces a new list. It is the single most common pattern
in this codebase.

A simple one filters file paths to directories only:

```python
runs = sorted(
    [p for p in OUTPUTS_DIR.glob("option2_*") if p.is_dir()],
    key=lambda p: p.name,
    reverse=True,
)
```

[`scripts/dashboard/lib.py:84-88`](../../scripts/dashboard/lib.py)

Read it as: "for each `p` in the glob result, if `p.is_dir()`, keep it."
The result is a list passed straight to `sorted`.

A more involved one cleans column names while reading the raw CSV:

```python
df.columns = [clean_text(c) for c in df.columns]
empty_unnamed = [c for c in df.columns if c.lower().startswith("unnamed") and (df[c].astype(str).str.strip() == "").all()]
```

[`scripts/option2_pipeline.py:377-378`](../../scripts/option2_pipeline.py)

The first line rebuilds the column index by applying `clean_text` to every
name. The second filters columns whose name starts with `"unnamed"` *and*
whose values are all empty. Two conditions joined with `and` — that is
how comprehensions express compound filters.

You will also see the bare list comprehension that splits a label and
keeps only non-empty parts:

```python
parts = [p for p in want_label.split("_") if p]
```

[`scripts/dashboard/lib.py:676`](../../scripts/dashboard/lib.py)

The condition `if p` is truthiness — empty strings are falsy in Python, so
this drops them.

## Dict comprehensions: the filter-and-rebuild pattern

Dict comprehensions use the same shape with key/value pairs:
`{k: v for ... in ... if ...}`. The pipeline's column resolver builds a
case-insensitive lookup table this way:

```python
lowered = {c.lower().strip(): c for c in df.columns}
```

[`scripts/option2_pipeline.py:333`](../../scripts/option2_pipeline.py)

Each iteration produces one `(key, value)` pair: the lowercased,
stripped column name maps to the original column name. The original case
is preserved as the value so the caller can index `df[name]` directly.

The dashboard's other-files grouper uses an explicit mapping rather than a
comprehension because the keys are hand-listed:

```python
return {
    "json": sorted(p.name for p in run_dir.glob("*.json")),
    "jsonl": sorted(p.name for p in run_dir.glob("*.jsonl")),
    "html": sorted(p.name for p in run_dir.glob("*.html")),
    "xlsx": sorted(p.name for p in run_dir.glob("*.xlsx")),
    "md": sorted(p.name for p in run_dir.glob("*.md")),
    "png": sorted(p.name for p in run_dir.glob("*.png")),
}
```

[`scripts/dashboard/lib.py:193-200`](../../scripts/dashboard/lib.py)

Each value is itself a generator expression `(p.name for p in
run_dir.glob(...))` passed to `sorted`. Generator expressions use
parentheses instead of brackets and produce values lazily — they do not
build an intermediate list when the consumer (`sorted`) only needs to
iterate once.

## `Counter` from collections: frequency tables

When you need to count things, reach for `collections.Counter`. It is a
`dict` subclass that initialises missing keys to zero and adds a
`.most_common(n)` method.

The taxonomy builder uses it inside `label_cluster`:

```python
from collections import Counter

# ...

tokens: Counter[str] = Counter()
for text in texts:
    for token in re.findall(r"[A-Za-z][A-Za-z\-']{2,}", text.lower()):
        if token in STOPWORDS or len(token) <= 3:
            continue
        tokens[token] += 1
top = [tok for tok, _ in tokens.most_common(top_n)]
return "_".join(top) if top else "misc"
```

[`scripts/build_user_wants_taxonomy.py:430-437`](../../scripts/build_user_wants_taxonomy.py)

Three things to notice.

`tokens: Counter[str] = Counter()` annotates the variable as a Counter
of string keys. The annotation is for readers and IDEs; Python itself
ignores it at runtime.

`tokens[token] += 1` is the core idiom. With a plain dict you would have
to write `tokens[token] = tokens.get(token, 0) + 1` or use
`defaultdict(int)`. Counter handles the missing-key case for free.

`tokens.most_common(top_n)` returns a list of `(key, count)` tuples sorted
by count descending. The tuple unpacking `for tok, _ in ...` discards the
count (we already used it for ranking) and keeps just the token. The
underscore is the conventional "I don't care about this value" name.

The same script uses `Counter` again inside `summarize` to build per-cluster
job histograms:

```python
f"{j}:{c}" for j, c in Counter(cluster_jobs).most_common(3)
```

[`scripts/build_user_wants_taxonomy.py:586`](../../scripts/build_user_wants_taxonomy.py)

`Counter(cluster_jobs)` builds the histogram in one call from any iterable.
The expression `f"{j}:{c}"` reformats each pair into the
`"recover_access:29"` micro-format that the dashboard later parses.

## Sets for fast `in` checks

A set is an unordered collection with O(1) average membership testing.
That is its superpower: `value in some_set` is constant-time, regardless
of set size, while `value in some_list` is O(n) and slow.

The LLM extractor uses a set as a blacklist of generic phrases the model
keeps emitting:

```python
GENERIC_PHRASES = {
    "unknown",
    "infer goal",
    "resolve issue",
    "analyze",
    "investigate",
    "n/a",
    "none",
    "fix issue",
    "block user",
    "unblock user",
    "account restored",
    "ban audit",
    "ban verification",
    "ban resolution",
    "improve user experience",
    "improve dispute resolution process",
    "review rule layer and data integrity",
}
```

[`scripts/llm_extract_rich_tickets.py:189-207`](../../scripts/llm_extract_rich_tickets.py)

The literal `{...}` syntax with no colons creates a set. (With colons it
would be a dict.) Note: an empty `{}` is a dict, not a set; for an empty
set you write `set()`.

The check is one line:

```python
if normalized in GENERIC_PHRASES:
```

[`scripts/llm_extract_rich_tickets.py:820`](../../scripts/llm_extract_rich_tickets.py)

If the model's output normalises to anything in the blacklist, the
extractor flags it and falls back to a more careful re-prompt.

The taxonomy builder uses sets for the same reason in `STOPWORDS`:

```python
STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "are", "was", "were",
    "have", "has", "had", "you", "your", "but", "not", "can", "could", "should",
    "would", "they", "them", "their", "there", "any", "all", "into", "out",
    "user", "users", "ticket", "tickets", "support", "system", "issue", "issues",
    "feature", "process", "provide", "improve", "implement", "create", "ensure",
    "clear", "clarity", "options", "available", "make", "more", "better",
    "ban", "bans", "banned", "block", "blocked", "blocking",
}
```

[`scripts/build_user_wants_taxonomy.py:376-384`](../../scripts/build_user_wants_taxonomy.py)

The `if token in STOPWORDS` check inside the inner loop runs once per
token across the entire dataset — measured in millions of calls. With a
set it is fast. With a list it would be the bottleneck.

The dashboard uses the same technique for cluster-label cleanup in
`_FRIENDLY_STOP` at
[`scripts/dashboard/lib.py:613-623`](../../scripts/dashboard/lib.py). Same
purpose, same rationale.

## Dicts for code-to-human mapping

The dashboard maps machine codes to user-facing labels via a module-level
dict:

```python
DESIRE_LABELS = {
    "recover_access": "Recover account access",
    "clear_name_or_get_fairness": "Get fairness / appeal a ban",
    "earn_or_transact_money": "Earn or move money",
    "grow_audience_or_community": "Grow channel or group",
    "gain_status_or_privileges": "Gain SVIP / status",
    "protect_from_abuse_or_scam": "Protect from abuse / scam",
    "fix_product_or_technical_flow": "Report a product issue",
    "understand_rules_or_system_logic": "Understand the rules",
    "customize_identity_or_assets": "Customize profile / identity",
    "play_or_entertainment": "Play games / entertainment",
    "unclear_or_needs_llm": "Unclear (needs review)",
}
```

[`scripts/dashboard/lib.py:548-560`](../../scripts/dashboard/lib.py)

The lookup goes through one helper:

```python
def humanize_desire(value: str) -> str:
    if not isinstance(value, str):
        return ""
    return DESIRE_LABELS.get(value.strip(), value.replace("_", " ").capitalize())
```

[`scripts/dashboard/lib.py:563-586`](../../scripts/dashboard/lib.py)

`dict.get(key, default)` is the cleanest way to express "look up the key,
return the default if missing." The default here is a graceful fallback
that turns `"some_new_code"` into `"Some new code"` — important when the
pipeline introduces a new code before the dashboard's mapping is updated.

The same file also keeps `JOB_TITLE_PREFIX` at lines 591-605 for the same
purpose, plus `status_badge` defines a *function-local* dict at
[`scripts/dashboard/lib.py:840-848`](../../scripts/dashboard/lib.py) — when
a mapping is only used inside one function, defining it there signals the
limited scope.

## `is not None` matters in pandas land

A pandas DataFrame compared with `==` does element-wise comparison. So
`df == None` is *not* the same as `df is None`. The first returns a
DataFrame of booleans; the second returns a single boolean. When you want
to check "did this function return a DataFrame or `None`?", you must use
`is not None`.

The dashboard uses this everywhere:

```python
def maybe_load_csv(run_dir: Path, name: str) -> pd.DataFrame | None:
    path = run_dir / name
    if not path.exists():
        return None
    return load_csv(str(run_dir), name)
```

[`scripts/dashboard/lib.py:228-252`](../../scripts/dashboard/lib.py)

And the caller in `app.py`:

```python
def _first_existing(*names: str):
    for n in names:
        df = maybe_load_csv(run_dir, n)
        if df is not None:
            return df
    return None
```

[`scripts/dashboard/app.py:94-122`](../../scripts/dashboard/app.py)

Writing `if df:` instead of `if df is not None:` would raise the
infamous error: *"The truth value of a DataFrame is ambiguous."* That
error is pandas saying "I don't know whether `if df:` means `if
df.any()` or `if len(df):` or something else, so I refuse to guess." The
fix is always `is not None`.

The same rule applies to numpy arrays. When in doubt, use `is None` /
`is not None` for sentinel checks, even on plain Python objects — it is
identity comparison, faster, and cannot be overridden by `__eq__`.

## Putting it together

The four collection types map onto four jobs:

- **List comprehensions** for transforming an iterable into a filtered
  new list.
- **Dict comprehensions** for building lookup tables in one expression.
- **`Counter`** for frequency tables, with `.most_common` already built
  in.
- **`set`** for blacklists, stopword lists, and any "is this in the
  group?" check.
- **Plain `dict`** for code-to-human mappings and any other
  key-value table you reach for again and again.

Everything else (`OrderedDict`, `defaultdict`, `deque`,
`namedtuple`) is in the standard library if you need it, but the
codebase uses these five almost exclusively.

## Try it

From the repo root, write a small script that, for the latest run,
counts the top 10 most common values in the `primary_desire` column of
`enriched_tickets.csv`:

```bash
.venv/bin/python -c "
from collections import Counter
from pathlib import Path
import pandas as pd
runs = sorted(p for p in Path('outputs').glob('option2_*') if p.is_dir())
run = runs[-1]
df = pd.read_csv(run / 'enriched_tickets.csv')
counts = Counter(df['primary_desire'].dropna())
for code, n in counts.most_common(10):
    print(f'{code:<35} {n:>5}')
"
```

Now extend it: import `DESIRE_LABELS` from
`scripts.dashboard.lib` (you may need to add `scripts/` to your path) and
print the *human label* next to the code, falling back to a title-cased
form for unmapped codes. This is the same pattern `humanize_desire` uses.
