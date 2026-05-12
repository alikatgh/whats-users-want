# Module 02 — Data with pandas

This module turns the messy `data_2may.csv` ticket export into the clean,
typed, feature-rich DataFrame that everything else in the pipeline depends on.
Every lesson cites real lines from `scripts/option2_pipeline.py` and
`scripts/insight_layer.py`.

By the end of the module you will read those two scripts the way an engineer
who wrote them does — line by line, knowing why each `dtype=str`, `errors="coerce"`,
`groupby(..., dropna=False)`, `pd.cut`, and `pd.merge(..., how="left")` is
there, and what would break if it were not.

## Prerequisites

- [Module 01 — Python Foundations](../01-python-foundations/README.md). You
  need to recognise `pathlib.Path`, raw-string regex, comprehensions, and
  PEP 604 union types (`str | None`) without stopping to parse them.
- A working Python 3.10+ environment with the project's `requirements.txt`
  installed (`pandas`, `numpy` are the load-bearing pieces).
- One run of the pipeline already on disk — for example
  `outputs/option2_20260502_150055/`. The "Try it" exercises read CSVs from
  there.

## What you'll be able to do after this module

- Read a raw CSV the way [`read_raw_csv`](../../scripts/option2_pipeline.py)
  does — preserving 14-digit UIDs as strings, refusing to invent NaN, and
  surviving stray "Unnamed: N" columns Google Sheets dribbled in.
- Canonicalise a frame whose columns drift between English, Chinese and
  Russian into a stable snake_case schema.
- Build evidence flags, desire flags, urgency counts, and a 0–100
  `context_depth_score` from raw text using vectorised pandas operations.
- Use `groupby(...).agg(name=(col, fn))` named-aggregation, lambdas-inside-agg
  for share calculations, and `value_counts().head(N).index.tolist()` to
  produce manager and persona summary tables.
- Join Stage 1's `enriched_tickets.csv` to Stage 2's
  `bertopic_assignments.csv` with `pd.merge(..., how="left", left_on=..., right_on=...)`,
  knowing exactly what `NaN` means in the result.
- Build cross-tabs with `pd.crosstab(rows, cols)`, format share columns as
  `(s * 100).round(1).astype(str) + "%"`, bucket numeric scores with
  `pd.cut(..., bins=[...], labels=[...])`, and split numeric vs categorical
  columns automatically with `select_dtypes(include="number")`.

## Lessons

| # | Lesson | What it covers |
|---|---|---|
| 01 | [Reading messy CSV](01-reading-messy-csv.md) | `pd.read_csv` with `dtype=str` and `keep_default_na=False`. Why preserving strings matters for 14-digit UIDs, and how `read_raw_csv` rebuilds column names with `clean_text`. |
| 02 | [Cleaning and canonicalize](02-cleaning-and-canonicalize.md) | `canonicalize()` end to end: `first_existing(...)` for Chinese/English column variants, `pd.to_datetime(errors="coerce")`, `.isin([...])`, the `~` negation. |
| 03 | [Feature engineering](03-feature-engineering.md) | `featurize_tickets()` walked function-line by function-line. Regex counts, boolean flags, `pd.cut` for context bands, the 95th-percentile cap trick. |
| 04 | [Groupby and aggregations](04-groupby-and-aggregations.md) | Named-tuple `agg` patterns, per-UID `groupby` with `sort_values` inside the loop, `value_counts().head(N).index.tolist()`, the `top_join` helper. |
| 05 | [Merge and join](05-merge-and-join.md) | `pd.merge(..., how="left")` in production. Joining `bertopic_assignments.csv` into the enriched frame; `left_on` / `right_on` when names differ. |
| 06 | [Pivot, crosstab, categorical](06-pivot-crosstab-and-categorical.md) | `pd.crosstab` for the dashboard's heatmaps. The share-formatting idiom. Auto-detecting numeric vs categorical with `select_dtypes`. |

Each lesson ends with a runnable "Try it" against
`outputs/option2_20260502_150055/`.

## What's next

- [Module 03 — Text and NLP](../03-text-and-nlp/README.md) takes the
  `model_text` column built at the end of Lesson 03 and feeds it to TF-IDF
  and sentence-transformers.
- [Module 04 — Dimensionality and Clustering](../04-dimensionality-and-clustering/README.md)
  takes those embeddings, runs UMAP and HDBSCAN, and produces the very
  `bertopic_assignments.csv` you join on in Lesson 05.
