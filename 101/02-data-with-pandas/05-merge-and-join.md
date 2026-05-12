# Merging and joining DataFrames

## The problem

Stage 1 (`option2_pipeline.py`) writes `enriched_tickets.csv`: one row per
ticket, with the 25 derived columns from
[Lesson 03](03-feature-engineering.md). Stage 2 (`bertopic_from_run.py`)
reads the embeddings, runs BERTopic, and writes
`bertopic_assignments.csv`: one row per ticket again, but with three
*new* columns — `bertopic_topic` (the integer topic id), `Name`
(BERTopic's auto-generated topic label such as
`0_account_restore_deleted_number`), and `Representation` (the top
keywords for that topic).

Stage 3 (`insight_layer.py`) needs both. Every opportunity-backlog row
has to carry a human-readable topic name like
`0_account_restore_deleted_number`. Every per-ticket score has to be
attributable to a topic. The only sane way to combine the two is a
SQL-style left join on the `source_row` key both files preserved.

This lesson covers `pd.merge` in two real shapes: a name-name join in
`load_run` and a key-with-different-names join in `bertopic_from_run`.

## `pd.merge` in one paragraph

`pd.merge(left, right, how="left", on="key")` is the pandas equivalent
of SQL's `LEFT JOIN`. Every row of `left` survives. Matching columns
from `right` are appended to the result. Where there is no match in
`right`, the appended cells are `NaN`. The `how` parameter controls
which side's rows are kept: `"left"` keeps every left row,
`"right"` keeps every right row, `"inner"` keeps only matching rows,
`"outer"` keeps every row from both.

`on="key"` means both frames have a column with the same name. If the
keys are named differently — `left` has `bertopic_topic` and `right`
has `Topic` — you use `left_on="bertopic_topic", right_on="Topic"`
instead.

That is the whole API for the cases the project uses.

## `load_run` — joining BERTopic labels onto the enriched frame

```python
def load_run(run_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame | None, pd.DataFrame | None]:
    df = pd.read_csv(run_dir / "enriched_tickets.csv")
    df["source_row"] = df["source_row"].astype(str)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for col in ["is_resolved", "is_unresolved", *EVIDENCE_COLS, *DESIRE_COLS]:
        if col in df.columns:
            df[col] = coerce_bool(df[col])
    df["uid"] = df["uid"].fillna("").astype(str).str.replace(r"\.0$", "", regex=True).str.strip()
    ...

    bertopic_assignments = None
    if (run_dir / "bertopic_assignments.csv").exists():
        bertopic_assignments = pd.read_csv(run_dir / "bertopic_assignments.csv")
        bertopic_assignments["source_row"] = bertopic_assignments["source_row"].astype(str)
        keep = ["source_row", "bertopic_topic", "Name", "Representation", "Count"]
        df = df.merge(bertopic_assignments[keep], on="source_row", how="left")
        fallback_cluster = pd.to_numeric(df["cluster_id"], errors="coerce").fillna(-999).astype(int)
        topic_or_cluster = pd.to_numeric(df["bertopic_topic"], errors="coerce").fillna(fallback_cluster).fillna(-999).astype(int)
        df["issue_id"] = topic_or_cluster.astype(str)
        df["issue_label"] = df["Name"].fillna("cluster_" + fallback_cluster.astype(str))
    else:
        df["issue_id"] = df["cluster_id"].fillna(-999).astype(int).astype(str)
        df["issue_label"] = "cluster_" + df["issue_id"]
    return df, bertopic_assignments, bertopic_topics
```

[`scripts/insight_layer.py:169-261`](../../scripts/insight_layer.py)

Five things to notice.

### Same key, both sides cast to the same dtype

```python
df["source_row"] = df["source_row"].astype(str)
bertopic_assignments["source_row"] = bertopic_assignments["source_row"].astype(str)
```

Every CSV round-trip resets dtypes. If the left side reads
`source_row` as `int64` (because `read_csv` inferred numbers) and the
right side reads it as `object` (because some other row was non-numeric),
the merge silently produces an empty result on every row. The keys
"compare equal" element-wise, but only when they share a dtype.

The fix is to force both sides to `str` before merging. This is the
single most common merge bug in pandas, and the single most reliable
way to avoid it: explicit cast on both sides, then merge.

### Selecting the right-hand columns before merging

```python
keep = ["source_row", "bertopic_topic", "Name", "Representation", "Count"]
df = df.merge(bertopic_assignments[keep], on="source_row", how="left")
```

`bertopic_assignments` has more columns than we need (it duplicates
`manager`, `category`, `model_text`, etc., from the left). Passing
`bertopic_assignments[keep]` to `.merge` projects to just the columns
we want before the join. Without this, you end up with `manager_x` and
`manager_y` after the merge — pandas's automatic suffix when the same
column appears on both sides.

The general rule: select the right-hand columns to exactly the join
key plus the new columns you want. Do not let `.merge` decide what to
keep.

### `how="left"` is the default but always be explicit

```python
df = df.merge(bertopic_assignments[keep], on="source_row", how="left")
```

The default `how` is `"inner"`, which only keeps rows present in both
frames. For a left join, you have to ask for it. The pipeline is
explicit because (a) the intent is clearer to a reader, and (b) if
the next maintainer ever changes `how="left"` to `how="inner"`, every
ticket BERTopic skipped (in this run, 1,331 tickets ended up in the
noise bucket — but they are still in the assignments file with
topic = -1) would silently disappear from `df`.

In this project, `how="left"` is also a defensive choice. BERTopic
should produce one row per ticket, but if Stage 2 ever crashes
mid-run and writes a partial assignments file, `how="left"` keeps
every Stage 1 ticket and just leaves the new columns NaN for the
missing tickets.

### What `NaN` means after a left join

For the rows where the left key did not find a match on the right, the
right-hand columns become `NaN`. In `df` after the merge, that means
`bertopic_topic`, `Name`, `Representation`, and `Count` are all `NaN`
for any ticket BERTopic did not process.

The pipeline immediately handles this:

```python
fallback_cluster = pd.to_numeric(df["cluster_id"], errors="coerce").fillna(-999).astype(int)
topic_or_cluster = pd.to_numeric(df["bertopic_topic"], errors="coerce").fillna(fallback_cluster).fillna(-999).astype(int)
df["issue_id"] = topic_or_cluster.astype(str)
df["issue_label"] = df["Name"].fillna("cluster_" + fallback_cluster.astype(str))
```

Three idioms layered:

- `pd.to_numeric(s, errors="coerce")` parses what it can and turns the
  rest into `NaN`. The classic defensive numeric parse.
- `.fillna(fallback_cluster)` replaces NaN with the corresponding
  values from another Series (aligned by index). If BERTopic did not
  produce a topic for this row, fall back to Stage 1's `cluster_id`.
- `.fillna(-999).astype(int)` provides a sentinel for the case where
  even the fallback is missing.

The result: every row gets an `issue_id` (string) and an `issue_label`
(human readable). No rows are lost. No NaN survives into the
opportunity backlog.

### Two outputs from one merge

`load_run` returns three things: `df`, `bertopic_assignments`,
`bertopic_topics`. The merged `df` is the *combined* analysis frame.
The two raw CSVs are returned unchanged so callers can also inspect
them in their original shape. Returning both lets a Stage 3 routine
that needs raw topic-info do its own join later without reloading
disk. A small ergonomic detail.

## `bertopic_from_run.py` — joining when the keys have different names

```python
doc_topics = docs_df[["source_row", "manager", "category", "question_kind", "primary_desire", "context_depth_score", "is_unresolved", "model_text"]].copy()
doc_topics["bertopic_topic"] = topics
doc_topics = doc_topics.merge(
    topics_df[["Topic", "Name", "Representation", "Count"]],
    left_on="bertopic_topic",
    right_on="Topic",
    how="left",
).drop(columns=["Topic"])
doc_topics.to_csv(run_dir / "bertopic_assignments.csv", index=False)
```

[`scripts/bertopic_from_run.py:184-192`](../../scripts/bertopic_from_run.py)

The shape: `doc_topics` is one row per ticket, with a column called
`bertopic_topic` holding integer topic ids. `topics_df` is one row per
topic, with a column called `Topic` (BERTopic's own naming) holding
the same integers. We want to attach the topic name and representation
to each ticket.

```python
left_on="bertopic_topic",
right_on="Topic",
```

Different name on each side. `left_on` is the column on the left
frame, `right_on` is the column on the right frame. Both frames need
the column to be the same dtype (here both `int64`).

After the merge, you have *both* columns — `bertopic_topic` and
`Topic` — with identical values. The trailing `.drop(columns=["Topic"])`
removes the redundant one. Without that drop, every downstream consumer
would see two columns that mean the same thing and have to decide
which one to use.

This is the canonical pattern for "join on a key that's named
differently in each source." Common in real data because two
upstream pipelines named the same concept differently — Stage 1's
naming convention vs BERTopic's library convention.

## Order matters: which side is "left"?

`A.merge(B, how="left", on="key")` keeps every row of `A` and looks
for matches in `B`. If you swap the order — `B.merge(A, how="left",
on="key")` — you keep every row of `B` instead. Same data, different
result.

Two heuristics:

- The frame whose rows you must preserve goes on the *left*. In
  `load_run`, the left side is `df` (every ticket). The right side is
  `bertopic_assignments`. Tickets BERTopic did not process still
  survive the merge.
- The frame that adds *columns* to the other goes on the *right*. The
  output has the same row count as the left, but new columns from the
  right.

When you read a `merge` line, ask yourself: "What rows does this
preserve? What columns does it add?" The answer falls out of which
frame is left, which is right, and what `how` says.

## What about `pd.concat`? `df.join`?

The project uses `pd.merge` almost exclusively. For completeness:

- `pd.concat([a, b], axis=0)` stacks two frames vertically. Use this
  when you want to *append rows*. It is not a join.
- `pd.concat([a, b], axis=1)` stacks horizontally by index. Equivalent
  to an outer join on the index. Useful but rare in this pipeline.
- `df.join(other, on=col)` is a thin wrapper around `merge` that
  defaults to joining on the *index* of `other`. `insight_layer.py`
  uses it once when the right-hand side is a Series indexed by a
  multi-key tuple
  ([`scripts/insight_layer.py:870-880`](../../scripts/insight_layer.py)).
  Functionally equivalent to `df.merge(other.reset_index(), on=col)`.
  Use whichever reads better.

For the everyday "attach extra columns to my frame" job, `pd.merge`
with explicit `how`, `on` (or `left_on`/`right_on`), and projected
right-hand columns is the right choice every time.

## Common merge mistakes you should learn to spot

1. **Mismatched key dtypes.** The merge runs without error but
   produces NaN on every right-hand column. Fix: cast both sides to
   the same dtype before merging.
2. **Forgetting `how="left"`.** The default is `"inner"`, which
   silently drops left-only rows. Fix: always pass `how` explicitly.
3. **Duplicate keys on the right.** A right-hand frame with two rows
   for the same key produces two output rows for every left row that
   matched. The output gets bigger than the left. Fix: deduplicate
   the right side before merging, or use `validate="m:1"` to make
   pandas raise.
4. **Letting pandas choose suffixes.** When both frames have a column
   called `manager`, the result has `manager_x` and `manager_y`. Fix:
   project the right side to just the columns you need before
   merging.

## Try it

```bash
.venv/bin/python -c '
import pandas as pd
from pathlib import Path

run = Path("outputs/option2_20260502_150055")

enriched = pd.read_csv(run / "enriched_tickets.csv", low_memory=False)
enriched["source_row"] = enriched["source_row"].astype(str)
print("enriched rows:", len(enriched))

assigns = pd.read_csv(run / "bertopic_assignments.csv")
assigns["source_row"] = assigns["source_row"].astype(str)
print("bertopic_assignments rows:", len(assigns))

# Mirror the load_run merge.
keep = ["source_row", "bertopic_topic", "Name", "Representation", "Count"]
merged = enriched.merge(assigns[keep], on="source_row", how="left")
print("merged rows:", len(merged))
print("rows with no bertopic match:", merged["bertopic_topic"].isna().sum())

# Top 5 topics by ticket count, post-merge.
top = (
    merged.dropna(subset=["Name"])
    .groupby("Name")
    .size()
    .sort_values(ascending=False)
    .head(5)
)
print("\nTop 5 topics in the merged frame:")
print(top)

# Now join to the topic-level table by a differently-named key.
topics = pd.read_csv(run / "bertopic_topics.csv")
print("\nbertopic_topics rows (topics, not tickets):", len(topics))
joined = merged.merge(
    topics[["Topic", "Count"]].rename(columns={"Count": "topic_size"}),
    left_on="bertopic_topic",
    right_on="Topic",
    how="left",
).drop(columns=["Topic"])
print("rows after second merge (should equal merged rows):", len(joined))
'
```

What you should see:

- `enriched rows` and `bertopic_assignments rows` are both 6,728.
  Both files cover the whole corpus.
- `merged rows` is also 6,728. Left join preserved every ticket.
- `rows with no bertopic match` is 0 for this run, because Stage 2
  processes every ticket. If a future run crashes mid-Stage-2, this
  number would be non-zero — and the `fillna` chain in `load_run`
  would substitute Stage 1's `cluster_id` for those rows.
- The top topics are `-1_url_group_imo_screen` (1,331 tickets, the
  noise bucket), `0_account_restore_deleted_number` (~536),
  `1_diamonds_buy_buy diamonds_money` (~481),
  `2_scammed_deceived_dealer_rubles` (~235), and
  `3_lim_992932223648_998934555570_ticket` (~233).

The second merge — left_on/right_on — should produce the same row
count as `merged`. If it does not, the keys probably have mismatched
dtypes.

[Lesson 06](06-pivot-crosstab-and-categorical.md) takes a step back
from joins and shows the cross-tabulation idioms the dashboard uses
on the merged frame.
