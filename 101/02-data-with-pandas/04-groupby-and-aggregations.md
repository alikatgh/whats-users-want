# Group-by and aggregations

## The problem

You have an enriched per-ticket frame from
[Lesson 03](03-feature-engineering.md). 6,728 rows, ~25 derived columns.
Now you want to answer questions one row higher:

- *Per manager*, how many tickets did they handle, what's their average
  `context_depth_score`, what share of their tickets carry a URL?
- *Per repeat user*, what persona do they fit, what's their average
  context score across their tickets, which managers have they spoken
  with, what desires keep coming up?

Both are `groupby` problems. Both need named aggregations. Both need
share calculations expressed as `(boolean column).mean()`. Both need a
helper to render "top N most frequent values" as a single CSV cell.

This lesson walks `build_manager_summary` from `option2_pipeline.py` and
`build_repeat_user_personas` from `insight_layer.py`. Together they
cover every groupby pattern the project uses.

## `build_manager_summary` — named aggregations and lambdas

```python
def build_manager_summary(df: pd.DataFrame) -> pd.DataFrame:
    grouped = df.groupby("manager", dropna=False)
    summary = grouped.agg(
        tickets=("source_row", "count"),
        unique_users=("uid", lambda s: s.replace("", np.nan).nunique()),
        avg_context_score=("context_depth_score", "mean"),
        median_context_score=("context_depth_score", "median"),
        forensic_share=("context_depth_band", lambda s: (s == "forensic").mean()),
        rich_or_forensic_share=("context_depth_band", lambda s: s.isin(["rich", "forensic"]).mean()),
        avg_char_count=("char_count", "mean"),
        avg_line_count=("line_count", "mean"),
        url_share=("has_url", "mean"),
        image_evidence_share=("has_image_url", "mean"),
        timestamp_share=("has_timestamp", "mean"),
        room_id_share=("has_room_or_group_id", "mean"),
        user_claim_share=("has_user_claim", "mean"),
        ban_reason_share=("has_ban_reason_language", "mean"),
        unresolved_share=("is_unresolved", "mean"),
    ).reset_index()
    for col in summary.columns:
        if col.endswith("share") or col.startswith("avg") or col.startswith("median"):
            summary[col] = summary[col].astype(float).round(4)
    return summary.sort_values(["avg_context_score", "tickets"], ascending=[False, False])
```

[`scripts/option2_pipeline.py:792-848`](../../scripts/option2_pipeline.py)

Five things to internalise.

### `groupby("manager", dropna=False)`

`df.groupby(col)` partitions the rows by the unique values of `col`.
Calling an aggregation method on the result produces one row per group.

The default `dropna=True` would silently throw away rows where
`manager` is `NaN`. In a corpus where manager is sometimes blank
because the ticket was filed without a handler, that means the
"unhandled" tickets vanish from the summary. `dropna=False` keeps a
group keyed by `NaN` (or, after `canonicalize`, the empty string),
preserving every row.

The shape rule: groupby preserves rows. If you start with 6,728 tickets
and 47 distinct managers, you end with 47 rows after aggregating. If
you start with 6,728 tickets and `dropna=True` drops 53 rows because
their manager is NaN, you end with 46 rows and 6,675 tickets accounted
for. The difference between 6,728 and 6,675 is invisible in the result
table — a quiet bug that only shows up when somebody asks "wait, why
don't these counts add up to the corpus size."

### Named-tuple aggregation: `name=(column, fn)`

```python
tickets=("source_row", "count"),
avg_context_score=("context_depth_score", "mean"),
```

Each keyword argument becomes a column in the result. The tuple
`(source_column, aggregation_function)` says "apply this function to
that column within each group." The function can be a string name
(`"count"`, `"mean"`, `"median"`, `"sum"`, `"first"`, `"nunique"`) that
pandas dispatches to optimized C paths, or a callable.

String names are faster. Use them whenever the aggregation has a
built-in name. Lambdas are for the cases that do not — sharing,
filtering by value, transforming before aggregating.

### Lambdas for share calculations

```python
forensic_share=("context_depth_band", lambda s: (s == "forensic").mean()),
rich_or_forensic_share=("context_depth_band", lambda s: s.isin(["rich", "forensic"]).mean()),
```

The trick: a boolean Series has `True` and `False` values; True is 1
and False is 0 in pandas arithmetic; `.mean()` therefore returns the
share that are True. So "share of this manager's tickets that landed
in the forensic band" is a single chained expression.

`s.isin([...])` generalises this to any membership: "share that landed
in *either* rich or forensic." Same `.mean()` trick, two-element list.

This boolean-to-share idiom shows up everywhere in the pipeline. Worth
internalising.

### Lambda for "unique non-empty UIDs"

```python
unique_users=("uid", lambda s: s.replace("", np.nan).nunique()),
```

`nunique()` counts distinct values. By default it includes the empty
string, which would lump every anonymous ticket into one phantom
"empty-UID user." The fix: replace `""` with `np.nan`, then `nunique`
skips NaN by default. Two operations chained in one expression, no
intermediate variable, no copy of the column.

### `is_unresolved` as a share

```python
unresolved_share=("is_unresolved", "mean"),
```

`is_unresolved` is a boolean column produced back in
[`canonicalize`](../../scripts/option2_pipeline.py). `.mean()` on a
boolean Series gives the share. This single line is "what fraction of
this manager's tickets are still open?" — exactly what you would
compute by hand if you had to.

### Rounding on the way out

```python
for col in summary.columns:
    if col.endswith("share") or col.startswith("avg") or col.startswith("median"):
        summary[col] = summary[col].astype(float).round(4)
```

Aggregation produces noisy floats (`0.4566123498723…`). The CSV reader
on the other side only wants four decimal places. The naming convention
makes the loop trivial: any column whose name ends in `share` or
starts with `avg`/`median` is rounded.

### Sorting by two columns

```python
return summary.sort_values(["avg_context_score", "tickets"], ascending=[False, False])
```

`sort_values` accepts a list of column names and a matching list of
booleans. Both descending here. Albert (the team's most prolific and
detail-heavy manager in this corpus) sits at row 0 with about 2,247
tickets and an `avg_context_score` near 25.3.

## Aggregating by groupby on a `Series`, not just a column

A small but useful side trick from elsewhere in the pipeline:

```python
mix = df.groupby(["category", "question_kind"])["context_depth_score"].mean().rename("mix_avg")
scored = df.join(mix, on=["category", "question_kind"])
```

[`scripts/insight_layer.py:870-880`](../../scripts/insight_layer.py)

When you select a single column off a groupby (`grouped["x"]`), the
aggregation returns a *Series* indexed by the groupby keys, not a
DataFrame. That Series has a `.rename(...)` method that gives it a
name, after which `df.join(mix, on=[...])` aligns it back onto the
original frame keyed by the groupby columns. This is how the pipeline
computes "context score minus the average for tickets of the same
category and question_kind" — a non-parametric residual without
running a regression. We touch joins properly in [Lesson 05](05-merge-and-join.md).

## `build_repeat_user_personas` — group iteration with `.mode()` and two `sort_values`

```python
def build_repeat_user_personas(df: pd.DataFrame) -> pd.DataFrame:
    work = df[df["uid"].ne("")].copy()
    rows = []
    for uid, sub in work.groupby("uid"):
        if len(sub) < 2:
            continue
        ordered = sub.sort_values("date")
        span = (ordered["date"].max() - ordered["date"].min()).days if ordered["date"].notna().all() else np.nan
        examples = ordered.sort_values("context_depth_score", ascending=False).head(2)["question_flat"].map(compact_example).tolist()
        rows.append(
            {
                "uid": uid,
                "persona": persona_for_user(sub),
                "tickets": int(len(sub)),
                "active_days_span": None if pd.isna(span) else int(span),
                "first_date": ordered["date"].min().date() if ordered["date"].notna().any() else "",
                "last_date": ordered["date"].max().date() if ordered["date"].notna().any() else "",
                "unresolved_share": round(float(sub["is_unresolved"].mean()), 4),
                "avg_context_score": round(float(sub["context_depth_score"].mean()), 2),
                "managers_seen": top_join(sub["manager"], 5),
                "top_desires": top_join(sub["primary_desire"], 5),
                "top_issues": top_join(sub["issue_label"], 5),
                "high_context_example_1": examples[0] if len(examples) > 0 else "",
                "high_context_example_2": examples[1] if len(examples) > 1 else "",
            }
        )
    return pd.DataFrame(rows).sort_values(["tickets", "unresolved_share", "avg_context_score"], ascending=False)
```

[`scripts/insight_layer.py:745-809`](../../scripts/insight_layer.py)

The same shape — group then summarise — but with logic too rich for
`agg`. Sometimes you have to iterate.

### Iterating with `for uid, sub in df.groupby(col)`

`groupby` is iterable. Each iteration yields `(group_key, sub_dataframe)`.
Inside the loop, `sub` is a real DataFrame containing only that user's
rows, with the same columns and dtypes as `work`. You can sort, slice,
filter, aggregate it however you want.

The `len(sub) < 2: continue` guard skips one-shot users — without it
we would emit a "persona" row for every customer in the dataset, which
defeats the point of "repeat users."

### Two `sort_values` passes inside the loop

```python
ordered = sub.sort_values("date")
span = (ordered["date"].max() - ordered["date"].min()).days
...
examples = ordered.sort_values("context_depth_score", ascending=False).head(2)
```

Both sorts happen *within one user's slice*, not across the whole
frame. They are cheap because the slice is small. Each sort answers a
different downstream question:

- Sort by date → first date, last date, span between them.
- Sort by `context_depth_score` descending → top-2 best-documented
  tickets to use as exemplars for that user.

Two sorts, two purposes, no conflict. You can `sort_values` as many
times as you need on the same DataFrame; each call returns a new
sorted view.

### Date-arithmetic and `.dt.date`

```python
span = (ordered["date"].max() - ordered["date"].min()).days
ordered["date"].min().date()
```

Subtracting two pandas `Timestamp` values gives a `Timedelta`, whose
`.days` attribute is the integer day count. `Timestamp.date()` (no
parens omission — it is a method) converts to a Python `datetime.date`
that serialises to `2026-04-01` rather than `2026-04-01 00:00:00`.

The `if ordered["date"].notna().all()` guard is important: if any of
the user's date values failed to parse, `.max() - .min()` would
involve `NaT` and produce a misleading span. Skip the calculation if
any date is missing.

### `.mode().iloc[0]` for "most common value, but in a Series"

```python
sub["issue_label"].mode().iloc[0] if not sub["issue_label"].mode().empty else str(issue_id)
```

[`scripts/insight_layer.py:560`](../../scripts/insight_layer.py)
(used in `build_opportunity_backlog`, same pattern as in personas)

`.mode()` returns a Series of the most common value(s) — plural,
because there can be ties. `.iloc[0]` picks the first one. The guard
is for the empty-Series case where the column was all-NaN; we fall
back to a string version of the issue id.

This is the canonical "give me the most frequent label" pattern when
you do not want a value-count Series, just one value.

### `value_counts().head(N).index.tolist()`

`top_join` is a tiny helper that the personas builder uses three
times:

```python
def top_join(series: pd.Series, n: int = 4) -> str:
    values = series.dropna().astype(str)
    values = values[values.str.strip().ne("")]
    if values.empty:
        return ""
    return ", ".join(values.value_counts().head(n).index.tolist())
```

[`scripts/insight_layer.py:264-303`](../../scripts/insight_layer.py)

The chain in the last line is one of the most common pandas idioms in
the project:

- `value_counts()` returns a Series of frequencies sorted descending,
  indexed by the values themselves.
- `.head(n)` keeps the top `n` rows.
- `.index` extracts the values (the counts are in `.values`).
- `.tolist()` converts the pandas Index to a plain Python list.
- `", ".join(...)` produces the final string.

Read the personas output to see the result. From
`outputs/option2_20260502_150055/repeat_user_personas.csv`, the most
prolific repeat user (`uid=1115686439938544`, persona
`creator_channel_operator`, 70 tickets across 292 active days) shows
`managers_seen = "Danila, Albert, Leonid"` — three names joined by
commas, in descending frequency. That string was assembled by the
above five-method chain.

The two-step filtering — `dropna()` then drop-empty-strings via the
boolean mask `values[values.str.strip().ne("")]` — is doing the same
job `unique_users` did with `replace("", np.nan).nunique()` in the
manager summary: pandas treats `NaN` and `""` as distinct, but for
"who has this user actually worked with" we want neither.

## When to use `.agg`, when to iterate

`build_manager_summary` uses `.agg(named=(col, fn))` because every
output column is either a basic statistic (count, mean, median) or a
share that fits in one lambda. The function knows nothing about
relationships between rows of the same manager — every metric is
independent.

`build_repeat_user_personas` iterates because:

- It needs to sort each group two different ways, for two different
  outputs.
- It needs to call `persona_for_user(sub)` — a function that inspects
  the *whole* sub-DataFrame and returns one string. That cannot be
  expressed as `agg`.
- It needs to extract the top-2 `context_depth_score` rows' question
  text, which requires sort-then-slice-then-map.

Rule of thumb: if every output column can be written as `(input_col,
function)`, use `agg`. If the per-group logic touches multiple columns
together or needs intermediate state, iterate the groupby.

## Try it

```bash
.venv/bin/python -c '
import pandas as pd
from pathlib import Path

run = Path("outputs/option2_20260502_150055")
df = pd.read_csv(run / "enriched_tickets.csv", low_memory=False)

print("rows:", len(df))
print("\nmanagers by avg_context_score (matches manager_context_quality.csv):")
summary = df.groupby("manager", dropna=False).agg(
    tickets=("source_row", "count"),
    avg_context_score=("context_depth_score", "mean"),
    forensic_share=("context_depth_band", lambda s: (s == "forensic").mean()),
    unresolved_share=("is_unresolved", lambda s: (s.astype(str).isin(["True", "1", "yes", "y"])).mean()),
).round(4).sort_values("avg_context_score", ascending=False)
print(summary.head(8))

print("\ntop 5 desires (matches desire_summary.csv ticket counts):")
desires = [c for c in df.columns if c.startswith("desire__")]
counts = pd.Series({d.replace("desire__", ""): df[d].astype(str).isin(["True", "1"]).sum() for d in desires})
print(counts.sort_values(ascending=False).head(5))
'
```

Expected: Albert at the top with about 2,247 tickets and
`avg_context_score` ≈ 25.29; Danila next with about 1,441 tickets and
`avg_context_score` ≈ 13.91. Top desires:
`grow_audience_or_community` (~2,143), `understand_rules_or_system_logic`
(~1,641), `clear_name_or_get_fairness` (~1,603), `earn_or_transact_money`
(~1,148), `fix_product_or_technical_flow` (~1,112).

If those numbers match the rows of `manager_context_quality.csv` and
`desire_summary.csv` in the run folder, your groupby and aggregation
chain reproduces the pipeline exactly.

[Lesson 05](05-merge-and-join.md) takes the per-ticket frame and joins
it to the BERTopic stage's output — the bridge between Stage 1
features and Stage 2 cluster labels.
