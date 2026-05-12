# 02 — Stage 2: `bertopic_from_run.py`

[Source](../../scripts/bertopic_from_run.py).

A small but important script. Reuses Stage 1's cached embeddings and runs BERTopic to produce **named** topics with c-TF-IDF labels. This is the validation step: if BERTopic discovers similar topics to the Stage 1 HDBSCAN clustering, that is independent confirmation.

## What it consumes

- `<run_dir>/semantic_cluster_assignments.csv` — the per-ticket model_text from Stage 1.
- `<run_dir>/embeddings_local.npy` — the cached 384-dim multilingual embeddings.

If the embedding file is missing (e.g., Stage 1 was run with `--embedding-backend tfidf`), this script raises `FileNotFoundError` and tells the user how to regenerate.

## Configuration

### `CountVectorizer` (lines 38-45)

Used by BERTopic's c-TF-IDF step to score word importance per topic.

```python
CountVectorizer(
    lowercase=True,
    stop_words="english",
    ngram_range=(1, 2),
    min_df=3,
    max_df=0.85,
    token_pattern=r"(?u)\b[\w][\w'-]{2,}\b",
)
```

### UMAP (lines 46-52)

Reduces 384-dim embeddings to 8 dimensions for HDBSCAN. Same pattern as Stage 1.

```python
UMAP(
    n_neighbors=25,
    n_components=8,
    min_dist=0.0,
    metric="cosine",
    random_state=42,
)
```

`min_dist=0.0` is BERTopic's recommended value when you want tight clusters in the reduced space (for clustering, not visualization).

### HDBSCAN (lines 53-58)

```python
HDBSCAN(
    min_cluster_size=min_topic_size,   # default 35 from CLI
    min_samples=max(5, min_topic_size // 3),
    metric="euclidean",
    prediction_data=False,
)
```

`min_topic_size=35` was tuned empirically: smaller values produce too many tiny topics, larger values miss real-but-small topics like the "pornography moaning" cluster (87 tickets).

### `BERTopic` (lines 59-67)

```python
BERTopic(
    embedding_model=None,           # we provide our own embeddings
    umap_model=umap_model,
    hdbscan_model=hdbscan_model,
    vectorizer_model=vectorizer,
    calculate_probabilities=False,  # we don't need probabilistic topic membership
    low_memory=True,
    verbose=True,
)
```

`embedding_model=None` is the key setting: we hand BERTopic the precomputed embeddings via `topic_model.fit_transform(docs, embeddings)`, so it does not download or run any embedding model itself.

## Outputs

After fitting:

1. **`bertopic_topics.csv`** — `topic_model.get_topic_info()`. One row per topic with columns:
   - `Topic` — int. -1 is the noise bucket.
   - `Count` — number of tickets in the topic.
   - `Name` — auto-generated like `1_diamonds_buy_buy diamonds_money` (top 4 c-TF-IDF terms).
   - `Representation` — top 10 representative terms.

2. **`bertopic_assignments.csv`** — per-ticket assignment, joined with the original metadata. Columns: `source_row, manager, category, question_kind, primary_desire, context_depth_score, is_unresolved, model_text, bertopic_topic, Name, Representation, Count`.

3. **`bertopic_barchart.html`** — interactive top-words-per-topic chart from `topic_model.visualize_barchart(top_n_topics=24)`.

4. **`bertopic_metadata.json`** — `{run_dir, docs, embeddings_shape, topics, generated_at}`.

5. **Appends "BERTopic Validation" section** to `executive_findings.md` listing the top 10 topics by count.

## Why this is "validation"

Stage 1 used HDBSCAN directly on UMAP-reduced embeddings without producing readable topic names. Stage 2 uses BERTopic, which:

- Takes the same embeddings.
- Runs HDBSCAN with similar parameters (different `min_cluster_size` though — 35 vs Stage 1's adaptive value).
- Adds c-TF-IDF naming so each topic has a label like `0_account_restore_deleted_number`.

If both steps assign the majority of tickets to the same conceptual buckets, the topics are real. The fact that the top BERTopic topics (`diamonds_buy_buy`, `account_restore`, `scammed_dealer`, etc.) overlap heavily with the largest Stage 1 clusters (cluster 6 = diamonds, cluster 13 = account restore, cluster 18 = scammed by dealer) is the validation.

## Limitation

The 1,381 tickets in topic `-1` are BERTopic's "I am not confident enough to label these" bucket. We do not throw them away; Stage 4 (`split_outlier_bucket.py`) re-clusters them with KMeans to surface 26 sub-themes. That is intentional engineering: keep BERTopic's conservative clustering, but do not lose the 21% of the dataset it left unlabelled.

## Command-line

```bash
python scripts/bertopic_from_run.py outputs/option2_<TIMESTAMP> [--min-topic-size 35]
```
