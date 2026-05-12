# Cross-tabs, share formatting, and column-type detection

## The problem

You have a per-ticket frame with columns like `want_title`, `user_emotion`,
`money_risk_level` (a 1–5 integer), and `Manager`. Product managers want
to see how those interact:

- Which discovered "wants" carry the most fearful, frustrated, or
  resigned tickets? (want × emotion)
- Which wants tend to come with high money risk? (want × money risk)
- Are some managers funnels for specific wants? (want × manager)

For a quick eye-roll across the matrix, no chart libraries, you reach
for `pd.crosstab(rows, cols)`. The dashboard's "What Users Want" page
calls it three times in a row, then renders each as a heatmap. This
lesson walks the patterns the dashboard uses, then shows how
`08_Browse_Data_Tables.py` auto-detects which columns are numeric and
which are categorical for its generic auto-charts.

## `pd.crosstab` is two-dimensional `value_counts`

```python
ct = pd.crosstab(filtered[heat_y_col], filtered["user_emotion"])
```

[`scripts/dashboard/pages/02_What_Users_Want.py:193`](../../scripts/dashboard/pages/02_What_Users_Want.py)

`pd.crosstab(rows, cols)` produces a DataFrame whose row index is the
unique values of the first argument, whose column index is the unique
values of the second, and whose cells are *counts of co-occurrences*.

If you have 100 tickets with `want_title="Restore deleted account"`
and `user_emotion="frustrated"`, you get the cell value 100 at row
`Restore deleted account`, column `frustrated`.

It is the standard input shape for a heatmap: rows on one axis, columns
on the other, a single number per cell. The dashboard wraps the result
in `px.imshow(ct.values, x=ct.columns, y=ct.index, ...)` and renders
each cell coloured by its count.

## Three crosstabs, three slightly different column types

```python
with tab1:
    if "user_emotion" in filtered.columns:
        ct = pd.crosstab(filtered[heat_y_col], filtered["user_emotion"])
        ...

with tab2:
    if "money_risk_level" in filtered.columns:
        ct = pd.crosstab(filtered[heat_y_col], filtered["money_risk_level"].astype(int))
        ...

with tab3:
    if "Manager" in filtered.columns:
        ct = pd.crosstab(filtered[heat_y_col], filtered["Manager"].fillna("(unknown)"))
        ...
```

[`scripts/dashboard/pages/02_What_Users_Want.py:191-237`](../../scripts/dashboard/pages/02_What_Users_Want.py)

Same shape, three small variations.

### `user_emotion` — already a string, no preprocessing

The `user_emotion` column is already short strings like `"frustrated"`,
`"hopeful"`, `"resigned"` produced upstream by an LLM extraction pass.
`pd.crosstab` takes both arguments as-is, builds the matrix, done.

### `money_risk_level` — cast to int first

`money_risk_level` is the LLM's 1-to-5 risk score. After a CSV
round-trip it can come back as a float (`1.0`, `2.0`, ...) because
pandas saw a few NaN values and upcast. Wrapping it in `.astype(int)`
fixes the column header in the output: `1, 2, 3, 4, 5` instead of
`1.0, 2.0, 3.0, 4.0, 5.0`. Cosmetic, but every dashboard chart gains a
little legibility.

This is also why the chart axis labels are built as
`x=[f"Risk {c}" for c in ct.columns]` — the columns are clean integers,
so a list comprehension formats them.

### `Manager` — fill missing values before tabulating

```python
ct = pd.crosstab(filtered[heat_y_col], filtered["Manager"].fillna("(unknown)"))
```

`pd.crosstab` drops rows where either argument is `NaN`. If you want
those rows to participate in the table — for example, to see how big
the "no manager assigned" bucket is — you have to substitute a
sentinel string before passing in. `.fillna("(unknown)")` is the usual
choice.

The same pattern shows up earlier in the page when building the
manager filter:

```python
managers = sorted(assignments["Manager"].fillna("(unknown)").astype(str).unique())
```

[`scripts/dashboard/pages/02_What_Users_Want.py:124`](../../scripts/dashboard/pages/02_What_Users_Want.py)

`.fillna(...)` then `.astype(str)` then `.unique()` then `sorted(...)`
— a four-step "give me a clean list of distinct values for this filter
widget" chain.

## Display formatting: `(s * 100).round(1).astype(str) + "%"`

```python
for col in ["share", "high_money_risk_share", "high_trust_risk_share"]:
    if col in display_taxonomy.columns:
        display_taxonomy[col] = (display_taxonomy[col] * 100).round(1).astype(str) + "%"
```

[`scripts/dashboard/pages/02_What_Users_Want.py:178-180`](../../scripts/dashboard/pages/02_What_Users_Want.py)

The `share` columns in `user_wants_taxonomy.csv` are stored as fractions
between 0 and 1. The dashboard reader is a human who wants to see
`12.4%`, not `0.124`. Three operations:

1. `(s * 100)` — scale fraction to percent.
2. `.round(1)` — keep one decimal place. This *is* the
   `Series.round` method, not Python's `round`; it works element-wise.
3. `.astype(str) + "%"` — turn the float into a string and append the
   percent sign. String concatenation is element-wise on a Series, so
   `series + "%"` appends the literal `%` to every cell.

The result is a string column you can drop straight into a Streamlit
dataframe. No formatter callback, no per-cell loop. Three chained
calls.

You will see this exact idiom in dashboard pages whenever a fractional
column needs to be readable. It is how the same `share=0.3185` you
saw in `desire_summary.csv` becomes `31.9%` on screen.

## Same trick for "Empty %"

```python
"Empty %": (df.isna().mean() * 100).round(1).astype(str) + "%",
```

[`scripts/dashboard/pages/08_Browse_Data_Tables.py:146`](../../scripts/dashboard/pages/08_Browse_Data_Tables.py)

`df.isna()` returns a frame of booleans (True where the value is null).
`.mean()` along the default axis = 0 gives, for each column, the mean
of the boolean column = the share of cells that are null. Multiply by
100, round, cast to string, append `%`. Same five-step chain, applied
to a different input.

## Bands referenced — `pd.cut` from Lesson 03

[Lesson 03](03-feature-engineering.md) introduced `pd.cut(...,
bins=[...], labels=[...])` for `context_depth_band`. The pattern shows
up again whenever the dashboard wants to bucket a numeric column into
named groups before crosstabbing. For instance, a hypothetical
"context band × emotion" crosstab would do:

```python
band_x_emotion = pd.crosstab(
    pd.cut(df["context_depth_score"], bins=[-1, 15, 35, 60, 101],
           labels=["thin", "basic", "rich", "forensic"]),
    df["user_emotion"],
)
```

The same `pd.cut` you used to engineer the column at write-time can be
applied at read-time to a numeric column you do not control. The
output of `pd.cut` is always a categorical, ready to feed straight
into `crosstab`.

## Detecting numeric vs categorical columns automatically

`08_Browse_Data_Tables.py` is the dashboard's generic CSV browser.
It does not know about the project's specific schema. It loads any
CSV in the run folder and decides on its own which columns to plot
as histograms, which as bar charts, and which to pair as scatters.

```python
numeric_cols = df.select_dtypes(include="number").columns.tolist()
categorical_cols = [
    c
    for c in df.columns
    if df[c].dtype == "object" and 1 < df[c].nunique() <= 80
]
```

[`scripts/dashboard/pages/08_Browse_Data_Tables.py:179-184`](../../scripts/dashboard/pages/08_Browse_Data_Tables.py)

Two patterns.

### `df.select_dtypes(include="number")`

`select_dtypes` returns a sub-DataFrame containing only columns whose
dtype matches the filter. `include="number"` matches `int8`, `int16`,
`int32`, `int64`, `float32`, `float64`, and so on — every numeric
dtype pandas recognises. `.columns.tolist()` gives the list of names.

Companion call: `select_dtypes(include="object")` for string columns.
The page uses it on line 158 to populate the "Text-search column"
dropdown — only string columns can be text-searched.

You can also pass `include` and `exclude` together:

```python
df.select_dtypes(include="number", exclude="bool")
```

…to get numeric columns excluding booleans. Useful because pandas
treats `bool` as numeric for some operations (it is a subtype of
`int64`) but you usually do not want a histogram of True/False.

### The "1 to 80 distinct values" categorical heuristic

```python
[c for c in df.columns if df[c].dtype == "object" and 1 < df[c].nunique() <= 80]
```

A categorical column for charting purposes is:

- string-typed (`object` dtype),
- has at least 2 distinct values (a constant column has 1 — useless to
  bar-chart), and
- has at most 80 distinct values (a free-text column has thousands —
  the bar chart would be unreadable).

The 80 boundary is empirical. A bar chart with 80 bars is dense but
readable; with 200 it is a wall of pixels. Tweak as you learn what
shape your data takes.

This is a *defensive heuristic*, not a contract. A column with exactly
80 distinct values that all happen to be free-text snippets would slip
through and produce an ugly chart. The page accepts that — the chart
is generated automatically and the user can ignore it.

The same pattern dynamically chooses which tabs to render:

```python
tabs_to_show = []
if numeric_cols:
    tabs_to_show.append("Distribution of one number")
if categorical_cols:
    tabs_to_show.append("Counts of one category")
if numeric_cols and len(numeric_cols) >= 2:
    tabs_to_show.append("Number vs number")
if numeric_cols and categorical_cols:
    tabs_to_show.append("Number across categories")
```

[`scripts/dashboard/pages/08_Browse_Data_Tables.py:186-194`](../../scripts/dashboard/pages/08_Browse_Data_Tables.py)

Show only the tabs the data supports. A CSV with no numeric columns
shows neither "Distribution" nor "Number vs number." A CSV with one
numeric column shows "Distribution" but not "Number vs number"
(because scatter needs ≥ 2 numeric axes).

This is conditional UI. The pandas part is the column-type
introspection.

## A small puzzle: when is an integer column "categorical"?

`money_risk_level` is stored as `int` (1 to 5). By
`select_dtypes(include="number")`, it is numeric and would be plotted
as a histogram by default. But `nunique()` on it is 5 — well within
the categorical heuristic's window.

The browser page punts on this: numeric columns get histogram charts.
The "What Users Want" page knows the domain and treats
`money_risk_level` categorically — that is why it casts to int and
runs `pd.crosstab` against it instead of treating it as a continuous
axis.

The lesson: a column's *dtype* answers "what type does pandas think
this is?" Its *cardinality* (`nunique()`) answers "how many distinct
values are there?" Charting decisions usually need both. Generic
tools key off dtype and accept some misclassifications. Hand-built
pages that know their domain key off semantics.

## Counts vs shares in a crosstab

`pd.crosstab(rows, cols)` returns counts. Sometimes you want shares
within each row instead. Two ways to get there:

- `pd.crosstab(rows, cols, normalize="index")` — pandas does it for
  you; rows now sum to 1.
- `ct = pd.crosstab(rows, cols); ct = ct.div(ct.sum(axis=1), axis=0)`
  — manual: divide every cell by its row total.

The dashboard sticks with raw counts because the heatmap displays them
as cell labels via `text_auto=True`. If it switched to shares, the
labels would need to be reformatted with the `(s * 100).round(1).astype(str) + "%"`
trick from earlier in this lesson.

## Try it

```bash
.venv/bin/python -c '
import pandas as pd
from pathlib import Path

run = Path("outputs/option2_20260502_150055")

# Use the BERTopic assignments — the file has Manager and Name columns.
assigns = pd.read_csv(run / "bertopic_assignments.csv")
print("rows:", len(assigns), "columns:", len(assigns.columns))

# Pick the 6 biggest topics so the crosstab is readable.
topic_sizes = assigns["Name"].value_counts().head(6)
print("\nbiggest topics:")
print(topic_sizes)

big = assigns[assigns["Name"].isin(topic_sizes.index)]

# Crosstab: topic Name × Manager.
ct = pd.crosstab(big["Name"], big["manager"].fillna("(unknown)"))
print("\nTopic × manager (top 6 topics):")
print(ct)

# Same trick: format a share column as percent.
shares = (ct.div(ct.sum(axis=1), axis=0) * 100).round(1).astype(str) + "%"
print("\nRow-normalised shares:")
print(shares)

# select_dtypes demo on the bertopic_topics.csv (mixed numeric and string).
topics = pd.read_csv(run / "bertopic_topics.csv")
print("\ntopics dtypes:")
print(topics.dtypes)
print("\nnumeric columns:", topics.select_dtypes(include="number").columns.tolist())
print("string columns:", topics.select_dtypes(include="object").columns.tolist())
'
```

You should see:

- The top topics are `-1_url_group_imo_screen` (the noise bucket,
  ~1,331 tickets), `0_account_restore_deleted_number` (~536),
  `1_diamonds_buy_buy diamonds_money` (~481),
  `2_scammed_deceived_dealer_rubles` (~235),
  `3_lim_992932223648_998934555570_ticket` (~233), and
  `4_frame_write_order_create` (~216).
- The crosstab is a tidy matrix of integer counts. Albert and Danila
  dominate most rows.
- The shares table has `%` suffixes on every cell.
- `bertopic_topics.csv` has `Topic` and `Count` as numeric (`int64`)
  and `Name`, `Representation`, `Representative_Docs` as `object`.
  `select_dtypes` partitions them cleanly, exactly the way the
  Browse Data Tables page does it.

Once those numbers match the dashboard's "What Users Want" → "Want ×
manager" tab, you have rebuilt a real dashboard chart from raw CSVs
in twenty lines.

## Where this leads

You now know enough pandas to read every line of `option2_pipeline.py`
and `insight_layer.py`. The remaining gaps are about *content*, not
syntax:

- [Module 03 — Text and NLP](../03-text-and-nlp/README.md) takes the
  `model_text` column you built at the end of [Lesson 03](03-feature-engineering.md)
  and feeds it to TF-IDF and multilingual sentence-transformers.
- [Module 04 — Dimensionality and Clustering](../04-dimensionality-and-clustering/README.md)
  takes those embeddings, runs UMAP and HDBSCAN, and produces the
  very `bertopic_assignments.csv` you joined onto your enriched frame
  in [Lesson 05](05-merge-and-join.md).

The reason this module ends here is that those two stages produce new
columns, but they consume the same DataFrame contract you have just
built. Once you can read, clean, featurise, group, merge, and pivot a
pandas frame the way the project does, you are ready to layer
embeddings and clusters on top.
