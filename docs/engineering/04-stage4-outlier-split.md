# 04 — Stage 4: `split_outlier_bucket.py`

[Source](../../scripts/split_outlier_bucket.py).

BERTopic's topic `-1` is the noise bucket — every ticket the algorithm could not confidently cluster. With 1,381 tickets in there, that "topic" is the largest single group in the dataset. We refuse to lose 21% of the data, so this script re-clusters just topic -1 with a forced KMeans.

## What it consumes

- `<run_dir>/semantic_cluster_assignments.csv` — Stage 1 output (provides model_text, manager, primary_desire, etc.)
- `<run_dir>/bertopic_assignments.csv` — Stage 2 output (provides bertopic_topic)
- `<run_dir>/embeddings_local.npy` — Stage 1 cached embeddings

## Pipeline

### `load_inputs(run_dir)` (lines 63-80)

Reads all three inputs, asserts the embeddings array length matches the semantic assignments length, returns `(semantic_df, bert_df, embeddings_array)`.

### `split_outliers(run_dir, n_subtopics, outlier_topic)` (lines 94-176)

1. Merge BERTopic assignments into the semantic frame.
2. Filter to rows where `bertopic_topic == outlier_topic` (default `-1`). Reset index — but **preserve the original embedding row** in a column called `embedding_row` so we can index back into the global embeddings array.
3. Refuse to split if there are fewer than 50 outlier rows.
4. Slice `embeddings[outlier.embedding_row]` and `normalize` (L2 row-wise).
5. Choose `k`:
   ```
   if --n-subtopics is provided:
       k = max(3, min(requested, max(3, n_docs // 12)))
   else:
       k = max(8, min(32, round(sqrt(n_docs / 2))))
   ```
   For 1,331 outlier docs, this yields `round(sqrt(665.5)) ≈ 26`.
6. Run **MiniBatchKMeans** with `n_clusters=k, random_state=42, n_init=30, batch_size=512`.
7. Compute per-row `confidence`:
   ```
   distances = km.transform(X)         # shape (n, k)
   chosen_dist = distances[i, label_i]
   confidence = 1 - chosen_dist / mean(distances over all clusters)
   confidence = clip(confidence, 0, 1)
   ```
   Higher confidence = the assigned cluster is much closer than the average cluster.
8. Build a TF-IDF over the outlier docs to derive **interpretable cluster names**:
   ```
   TfidfVectorizer(
       max_features=7000, min_df=3, max_df=0.85,
       ngram_range=(1, 2), lowercase=True,
       strip_accents="unicode", stop_words="english",
       token_pattern=r"(?u)\b[\w][\w'-]{2,}\b",
   )
   ```
   For each cluster, take the mean TF-IDF vector and pull the top 12 terms by score.
9. Compose `outlier_subtopic_label` like `outlier_13_voice_microphone_voice_room_room_can_t` using the `slug_terms` helper that picks the first 5 unique tokens.
10. Compute silhouette score on a 1,200-row cosine sample as a clustering-quality metric.

Returns `(assignments_df, summary_df, metrics_df)`.

### `write_refined_backlog(run_dir, assignments)` (lines 179-195)

Re-runs Stage 3's `build_opportunity_backlog` with one important change: replaces every ticket whose `issue_id == "-1"` (i.e., was in the BERTopic noise bucket) with `issue_id = "outlier_<sub_id>"` and `issue_label = outlier_<sub_id>_<terms>`. The result is a refreshed backlog where the previously-monolithic outlier topic is broken into 26 actionable rows.

This is why [refined_opportunity_backlog.csv](../../outputs/option2_20260502_150055/refined_opportunity_backlog.csv) has 79 rows while the original [opportunity_backlog.csv](../../outputs/option2_20260502_150055/opportunity_backlog.csv) has 54.

### `create_map(run_dir, assignments, embeddings)` (lines 198-224)

Produces an interactive 2D UMAP map of just the outlier tickets, colored by sub-theme label. UMAP parameters are similar to Stage 1 visualization: `n_components=2, n_neighbors=20, min_dist=0.08, metric="cosine"`.

### `write_outputs(...)` (lines 227-253)

CSV + Excel + DuckDB integration with the existing `analysis.duckdb`.

### `append_report(...)` (lines 256-291)

Adds an "Outlier Split" section to `executive_findings.md`, replacing any prior version with a marker-based split.

## Output files

- `outlier_subtopics.csv` — 26 sub-themes with size, share-of-outlier, avg confidence, avg context, top terms, top desires/managers/categories, four examples each
- `outlier_subtopic_assignments.csv` — 1,331 ticket → sub-theme assignments with confidence
- `outlier_split_metrics.csv` — silhouette + meta
- `refined_opportunity_backlog.csv` — Stage 3 backlog with the noise bucket replaced
- `outlier_subtopic_map.html` — interactive map
- `outlier_split_workbook.xlsx` — Excel with sheets `outlier_subtopics, assignments, metrics, refined_backlog`
- `outlier_split_metadata.json` — run config

## Why MiniBatchKMeans and not HDBSCAN here?

We deliberately *want* every ticket forced into a sub-theme. HDBSCAN would label some as noise again, producing nested noise — useless. KMeans guarantees full coverage. The trade-off is that KMeans clusters can be less semantically tight than HDBSCAN clusters; we mitigate by:

- Computing per-row confidence (lines 113-114). Low-confidence assignments can be filtered out at consumption time.
- Reporting silhouette score so we know how clean the partition actually is.
- Picking k from `sqrt(n/2)` rather than fixing it, so the granularity adapts to the data.

## Command-line

```bash
python scripts/split_outlier_bucket.py [outputs/option2_<TIMESTAMP>] \
  [--outlier-topic -1] [--n-subtopics N]
```

Defaults: latest run, BERTopic topic -1, automatic k.
