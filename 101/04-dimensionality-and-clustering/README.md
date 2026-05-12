# Module 04 — Dimensionality and Clustering

By the end of Module 03 you have a matrix of 6,669 vectors, 384 floats wide,
cached on disk as `embeddings_local.npy`. Each row is one ticket projected
into a multilingual semantic space.

This module is what happens when you try to draw lines around those vectors.
You will discover, immediately, that 384-dimensional Euclidean space behaves
nothing like the 2-D plane your intuition was built for. Distances flatten
out. Density loses meaning. Every point is roughly the same distance from
every other point, and clustering algorithms run blind.

The fix the pipeline uses, in this order: project to 8–10 dimensions with
UMAP, cluster with HDBSCAN, accept that 21% of tickets land in a noise
bucket on purpose, then either re-cluster that noise with KMeans or stitch
the whole thing together with BERTopic and c-TF-IDF labels.

## Prerequisites

- [Module 01 — Python Foundations](../01-python-foundations/README.md). NumPy
  slicing, optional-import patterns, argparse-driven CLI scripts.
- [Module 02 — Data with pandas](../02-data-with-pandas/README.md). `groupby`,
  `value_counts`, boolean masks, the `enriched_tickets.csv` schema.
- [Module 03 — Text and NLP](../03-text-and-nlp/README.md). What an
  embedding is, why `normalize_embeddings=True` makes cosine equal dot
  product, the per-cluster TF-IDF labelling trick.
- The `outputs/option2_20260502_150055/` run on disk. Every "Try it" loads
  files from there.

## What you'll be able to do after this module

- Explain why 384-D embeddings cluster badly without reduction
  (concentration of distances, every point is a hub, density estimators
  go silent).
- Read every UMAP and HDBSCAN argument in `cluster_texts` and
  `bertopic_from_run.py` and justify the choice.
- Defend the decision to leave 1,381 tickets in topic `-1` instead of
  forcing them into clusters.
- Recognise the three places the pipeline falls back to KMeans, and
  justify the `n_init` and `batch_size` choices.
- Compute `k = round(sqrt(n_docs / 2))` clamped to `[8, 32]` by hand and
  show why 1,331 outlier docs yield k = 26.
- Read the four-step BERTopic pipeline (embeddings → UMAP → HDBSCAN →
  c-TF-IDF) and read a topic name like `1_diamonds_buy_buy diamonds_money`
  as the c-TF-IDF top-word output.
- Compute a centroid as `embeddings[mask].mean(axis=0)` and a per-row
  centroid similarity, and explain why we sample 1,200 rows for silhouette.
- Read [`pages/06_Ticket_Map.py`](../../scripts/dashboard/pages/06_Ticket_Map.py)
  and explain why the X/Y axis numbers are meaningless even though
  relative positions are not.

## Lessons

| # | Lesson | What it covers |
|---|---|---|
| 01 | [Curse of dimensionality](01-curse-of-dimensionality.md) | Why 384-D vectors flatten distances, the "every point is a hub" problem, and why we project to 8-10 dims for clustering and 2 for visualization. |
| 02 | [UMAP](02-umap.md) | UMAP intuition; the three `UMAP(...)` calls in the pipeline (`n_components=2/8/10`); why `metric="cosine"`, `min_dist=0.0` for clustering. |
| 03 | [Density clustering (HDBSCAN)](03-density-clustering-hdbscan.md) | "Find dense regions, leave the rest as noise." `min_cluster_size`, `min_samples`, why noise is a feature, the 1,381-ticket noise bucket leading to Stage 4. |
| 04 | [KMeans fallback](04-kmeans-fallback.md) | When you fall back: small datasets, every-ticket-must-be-assigned. `MiniBatchKMeans(n_init=30, batch_size=512)`. The `sqrt(n_docs/2)` k heuristic. |
| 05 | [BERTopic and c-TF-IDF](05-bertopic-and-c-tfidf.md) | BERTopic stitches embeddings + UMAP + HDBSCAN + c-TF-IDF. The c-TF-IDF math. The 53-topic + topic-(-1) outcome. |
| 06 | [Cluster quality and centroids](06-cluster-quality-and-centroids.md) | Silhouette score (`(b-a)/max(a,b)`). Why sample to 1,200 rows. Centroid computation. Per-row similarity for representative examples. |

Each lesson ends with a runnable "Try it" against
`outputs/option2_20260502_150055/`.

## What's next

- [Module 05 — Statistics](../05-statistics/README.md) takes the cluster IDs
  and per-row attributes and runs significance tests.
- [Module 06 — LLMs and Prompts](../06-llms-and-prompts/README.md) shows how
  the 1,381 outlier tickets feed into a separate LLM extraction pass.
- [Module 09 — Streamlit Dashboards](../09-streamlit-dashboards/README.md)
  renders the 2-D UMAP scatter as the Ticket Map page.
