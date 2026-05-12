# 06 — Stage 6: `build_user_wants_taxonomy.py`

[Source](../../scripts/build_user_wants_taxonomy.py).

The smallest script. Re-embeds the LLM-extracted want/job/opportunity fields, clusters them, and labels each cluster.

## What it consumes

In priority order, the first existing file:

1. `<run_dir>/ollama_gemma3-4b_extractions.csv`
2. `<run_dir>/ollama_extractions.csv`
3. `<run_dir>/llm_extractions.csv`
4. `<run_dir>/rules_extractions.csv`

Plus optionally `<run_dir>/enriched_tickets.csv` for joining manager/category/date back.

## Pipeline

### 1. Build `_want_text` per row (`build_want_text`, lines 53-59)

Concatenates the four most signal-rich extracted fields with `" | "` separator, dropping empty/`nan`/`other`:

```
_want_text = "actual_user_want | job_to_be_done | product_opportunity | literal_request"
```

Why concatenate: redundancy. If the model under-specified one field, another carries the meaning. Embedding the joined string averages the signal.

### 2. Embed (`embed_texts`, lines 62-69)

```python
SentenceTransformer("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
.encode(texts, batch_size=32, show_progress_bar=False, normalize_embeddings=True)
```

Same model as Stage 1 / 2 / 4 for consistency. Embeddings are normalized so cosine and Euclidean give equivalent rankings.

### 3. Cluster (`cluster_wants`, lines 72-105)

Default mode is `auto`:

```python
HDBSCAN(
    min_cluster_size=min_cluster_size,
    min_samples=1,
    metric="euclidean",
    cluster_selection_method="eom",
    cluster_selection_epsilon=0.15,
)
```

After fitting, check whether HDBSCAN produced a usable taxonomy:

- If outlier count > 40% of points OR fewer than 8 clusters formed → fall back to KMeans.
- Otherwise keep HDBSCAN.

KMeans fallback uses adaptive k:

```python
n_clusters = max(10, min(20, len(embeddings) // 14))
KMeans(n_clusters=n_clusters, n_init="auto", random_state=42)
```

For the current 250-row dataset, HDBSCAN gave 6 clusters with 123 outliers (49% outlier rate), so KMeans fired with `k=17`.

CLI flags allow forcing:
- `--method kmeans --n-clusters 20` (force KMeans with k=20)
- `--method hdbscan --min-cluster-size 4` (force HDBSCAN, accept whatever it gives)

### 4. Compute centroids and per-row similarity (lines 132-141)

For each cluster, average the embeddings to get a centroid. For each row, compute cosine similarity to its assigned cluster's centroid. This is `centroid_similarity`. Rows with similarity near 1 are at the heart of the cluster; rows with low similarity are at the boundary.

### 5. Label each cluster (`label_cluster`, lines 119-126)

Tokenize the cluster's `_want_text` strings:

```python
re.findall(r"[A-Za-z][A-Za-z\-']{2,}", text.lower())
```

Drop project-specific stopwords (`STOPWORDS` set in lines 109-117) like "user", "ticket", "ban", "system", "improve", "implement", "create", etc. — these would dominate every cluster otherwise. Take the top 6 by frequency, join with `_`. Result: `account_access_recover_unban_regain_unblocked`.

### 6. Per-cluster summary (`summarize`, lines 128-228)

For each cluster, compute:
- `size`, `share`
- `top_jobs` — `Counter(cluster_jobs).most_common(3)` formatted as `"job:count, job:count, ..."`.
- `top_emotions` — same for emotions.
- `avg_money_risk`, `avg_trust_risk`, `avg_urgency`, `high_money_risk_share`, `high_trust_risk_share` — means of the 1-5 risk fields and the share with risk ≥ 4.
- Three example `_want_text` (sorted by `centroid_similarity` descending) — these are the most central tickets.
- Two example `support_next_step` — concrete operational actions.

### 7. Join back to enriched tickets (lines 222-235)

If `enriched_tickets.csv` is available, merge in `manager`, `Question`, `Status`, `Category`, `Date` for each assigned ticket. This is what powers the `want × manager` cross-tab in the Excel workbook.

### 8. Write outputs (`write_workbook`, `write_findings`)

Excel workbook has four sheets:
- **`taxonomy`** — one row per discovered want.
- **`assignments`** — one row per ticket (250 rows).
- **`want_x_emotion`** — pd.crosstab(want_label, user_emotion).
- **`want_x_money_risk`** — pd.crosstab(want_label, money_risk_level).
- **`want_x_manager`** — pd.crosstab(want_label, Manager).

Markdown report `user_wants_findings.md` lists each want with size, top jobs, emotions, risk averages, three examples, and a next-step example.

## Output files

- `user_wants_taxonomy.csv` — 17 rows for the latest run.
- `user_wants_assignments.csv` — 250 rows.
- `user_wants_workbook.xlsx`
- `user_wants_findings.md`
- `user_wants_metadata.json` — generation timestamp, source file, rows, clusters, outliers, min_cluster_size.

## Command-line

```bash
python scripts/build_user_wants_taxonomy.py <run_dir> \
  [--min-cluster-size 5] \
  [--method {auto,hdbscan,kmeans}] \
  [--n-clusters N]
```

## Design notes

- **Re-embedding**, not reusing Stage 1 embeddings: the LLM-extracted text is conceptually different from the raw ticket text. We want to cluster by *what the user wants*, not by *what the ticket mentions*.
- **Auto-fallback** because 250 docs is small for HDBSCAN. With more LLM extractions (1,000+), HDBSCAN should give better-shaped wants without the fallback.
- **No outlier subtopic split here**: if HDBSCAN keeps too many outliers, we fall back to KMeans rather than splitting separately. Different from Stage 4 because here we have only 250 docs total.
- **Cluster labels are heuristic** (top 6 distinctive tokens). They are deliberately not LLM-generated — we want stable, deterministic naming for the taxonomy itself.
