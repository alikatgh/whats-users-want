# 04 — KMeans Fallback

## The problem

HDBSCAN is the right algorithm when density is meaningful. It refuses
to cluster what it cannot cluster, returning the noise label `-1` and
saving the analyst from false confidence. That is its strength.

It is also a problem in three specific situations.

First, when density is not meaningful. On a tiny dataset — 250
LLM-extracted want strings — there are not enough points for HDBSCAN
to estimate density reliably. It either declares everything noise or
collapses to two mega-clusters.

Second, when you actually need every point assigned. The 1,381 tickets
HDBSCAN dumped into topic `-1` are useful as a triage signal, but
sooner or later a product manager wants to know what is in there. You
cannot present "1,381 unsorted tickets" as an output.

Third, when HDBSCAN is unavailable. Its C extension breaks across
Python and NumPy upgrades more often than the rest of the stack.
Production pipelines need a fallback.

KMeans solves all three. It forces every point into one of `k`
clusters. There is no noise bucket. It always finishes. It always
produces something interpretable. The cost is that "always produces
something" includes garbage when the data has no real cluster
structure — and you have to pick `k` yourself.

The pipeline uses KMeans (or its mini-batch variant) in three places.
This lesson walks through each.

## The intuition: nearest-centroid assignment

KMeans is the simplest serious clustering algorithm. Pick `k` random
centroids. Assign every point to the closest centroid. Move each
centroid to the mean of its assigned points. Repeat until nothing
moves. The result is a partition of the input space into `k` Voronoi
cells, each anchored at a centroid.

Two consequences fall out immediately. First, every point is in
exactly one cluster — there is no concept of noise or low confidence
in vanilla KMeans. Second, the algorithm assumes spherical clusters of
roughly equal size, because Voronoi cells around evenly-distributed
centroids look like that. Real text-embedding clusters are neither
spherical nor equal-sized, so KMeans always produces somewhat soft
assignments at the boundaries. That is a known limitation, accepted on
the grounds that "every point in some cluster" is more useful than
"perfect clustering of half the points".

## Place 1: the auto fallback in cluster_wants

The first KMeans call lives inside the user-wants taxonomy at
[scripts/build_user_wants_taxonomy.py:228-349](../../scripts/build_user_wants_taxonomy.py).
It is wrapped in an `auto` mode that tries HDBSCAN first and falls
back to KMeans if HDBSCAN's output is unusable. Read the whole
selection block:

```python
if method == "kmeans":
    from sklearn.cluster import KMeans

    n = n_clusters or max(8, min(24, len(embeddings) // 12))
    return KMeans(n_clusters=n, n_init="auto", random_state=42).fit_predict(embeddings)
try:
    import hdbscan

    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=min_cluster_size,
        min_samples=1,
        metric="euclidean",
        cluster_selection_method="eom",
        cluster_selection_epsilon=0.15,
    )
    labels = clusterer.fit_predict(embeddings.astype(np.float64))
    n_outlier = int((labels == -1).sum())
    n_clust = len({int(l) for l in labels if l != -1})
    if method == "auto" and (n_outlier > 0.4 * len(embeddings) or n_clust < 8):
        print(
            f"[info] HDBSCAN gave {n_clust} clusters / {n_outlier} outliers; "
            f"falling back to KMeans for denser taxonomy",
            file=sys.stderr,
        )
        from sklearn.cluster import KMeans

        n = n_clusters or max(10, min(20, len(embeddings) // 14))
        return KMeans(n_clusters=n, n_init="auto", random_state=42).fit_predict(embeddings)
    return labels
```

Two sanity checks decide the fallback. From the teaching note at
[scripts/build_user_wants_taxonomy.py:288-294](../../scripts/build_user_wants_taxonomy.py):

```python
# **The auto-fallback heuristic** is intentionally crude::
#
#     outliers > 40% of points  OR  clusters < 8  →  switch to KMeans
#
# Forty percent is a "this is unusable" line; eight is the
# minimum number of distinct "wants" that makes the resulting
# spreadsheet interesting to a product manager.
```

Forty percent outliers means HDBSCAN gave up. Fewer than eight clusters
means HDBSCAN collapsed everything into a small number of mega-blobs.
Either way, the answer is a denser KMeans partition.

The KMeans `k` is adaptive: `max(10, min(20, len(embeddings) // 14))`.
For our 250-row corpus this evaluates to `max(10, min(20, 17)) = 17`.
That is exactly what you see in the canonical output at
[outputs/option2_20260502_150055/user_wants_metadata.json](../../outputs/option2_20260502_150055/user_wants_metadata.json):

```json
{
  "rows": 250,
  "clusters": 17,
  "outliers": 0,
  "min_cluster_size": 5
}
```

`outliers: 0` is the giveaway. KMeans never produces outliers. If you
see zero in this field, the auto-fallback fired.

## Place 2: the MiniBatchKMeans fallback in cluster_texts

The second KMeans call is the safety net inside `cluster_texts`. If
HDBSCAN fails to import or crashes, the pipeline still has to produce
clusters. From
[scripts/option2_pipeline.py:1366-1373](../../scripts/option2_pipeline.py):

```python
except Exception as exc:
    print(f"[warn] HDBSCAN unavailable/failed: {exc}. Falling back to MiniBatchKMeans.", file=sys.stderr)
    from sklearn.cluster import MiniBatchKMeans

    k = max(8, min(35, int(math.sqrt(len(work) / 2))))
    clusterer = MiniBatchKMeans(n_clusters=k, random_state=42, n_init=20, batch_size=1024)
    labels = clusterer.fit_predict(reduced)
    probabilities = np.ones(len(work))
```

Two new things to notice.

`k = max(8, min(35, sqrt(n/2)))` is the `sqrt(n/2)` heuristic clamped
to `[8, 35]`. For 6,669 tickets that gives `max(8, min(35, 57)) = 35`.
The justification appears in `split_outlier_bucket.py` at
[scripts/split_outlier_bucket.py:213-217](../../scripts/split_outlier_bucket.py):

```python
# * Why ``sqrt(n)``? In clustering literature, "rule of thumb" choices
#   for ``k`` often grow as ``sqrt(n)`` because it gives roughly equal
#   weight to the number of clusters and the average cluster size: each
#   group ends up with about ``sqrt(n)`` items, which keeps both the
#   per-cluster sample and the number of clusters interpretable.
```

Each of `k` clusters has roughly `n/k = sqrt(n)` members on average,
and there are `sqrt(n)` clusters. Symmetric, interpretable, and within
the band of "I can scroll the spreadsheet without losing my place".

`MiniBatchKMeans` is the scalable variant. Plain KMeans recomputes
centroids by iterating over every point on every step. MiniBatch picks
a random subset of `batch_size` points per step, updates centroids
from just those, and accepts the small accuracy hit in exchange for an
order-of-magnitude speedup on large corpora.

`probabilities = np.ones(len(work))` is a placeholder so downstream
code can use the same column whether HDBSCAN or KMeans was used.
KMeans does not produce probabilities, so we record perfect confidence
for everything. Downstream sorting on this column becomes a no-op,
which is the desired behaviour.

## Place 3: the forced split in split_outliers

The third KMeans call is the headline of Stage 4. It does not fall
back from HDBSCAN; it explicitly refuses HDBSCAN. The 1,381 tickets in
the noise bucket are tickets HDBSCAN already declined to cluster. The
whole point of this stage is to use a different algorithm — one without
a noise option — and force every ticket into some sub-theme.

From [scripts/split_outlier_bucket.py:426-434](../../scripts/split_outlier_bucket.py):

```python
X = embeddings[outlier["embedding_row"].to_numpy()]
X = normalize(X)
docs = outlier["model_text"].fillna("").astype(str).tolist()
k = choose_k(len(outlier), n_subtopics)
km = MiniBatchKMeans(n_clusters=k, random_state=42, n_init=30, batch_size=512)
labels = km.fit_predict(X)
distances = km.transform(X)
confidence = 1 - (distances[np.arange(len(labels)), labels] / np.maximum(distances.mean(axis=1), 1e-9))
confidence = np.clip(confidence, 0, 1)
```

Three things differ from the `cluster_texts` fallback.

`n_init=30` instead of `n_init=20`. We are spending more compute on
finding a good initialisation because this is the production algorithm
for this data, not an emergency fallback. Each restart picks different
random initial centroids and runs the optimiser to convergence; the
final answer is the lowest-inertia of the 30 attempts.

`batch_size=512` instead of `1024`. The dataset is much smaller (1,331
rows after re-merging vs 6,669 in `cluster_texts`), so a smaller
mini-batch is appropriate.

A real per-row confidence, not a placeholder. Read the formula in plain
words from the teaching note at
[scripts/split_outlier_bucket.py:391-399](../../scripts/split_outlier_bucket.py):

```python
# **3. Per-row confidence.** ``km.transform(X)`` returns the
# ``(n_docs, k)`` matrix of distances from each row to each centroid.
# We take the distance to the *chosen* centroid for each row
# (``distances[np.arange(n), labels]``) and divide by the row's mean
# distance to all centroids. A row that is much closer to its own
# centroid than to the others gets a small ratio, so ``1 - ratio`` is
# close to 1 (high confidence). A row that is roughly equidistant from
# every centroid gets a ratio near 1, so confidence is near 0. We clip
# to ``[0, 1]`` because numerical noise can push it slightly outside.
```

This is a homemade replacement for HDBSCAN's `probabilities_`. KMeans
does not give us one, so we synthesise one out of distance ratios. It
is not statistically rigorous — it does not normalise to a probability
distribution — but it correctly orders the rows from "this ticket is
firmly in its sub-theme" to "this ticket is on the boundary of two".
That is enough for the dashboard to filter on.

## The k = sqrt(n/2) heuristic, in detail

Stage 4 chooses `k` with `choose_k` at
[scripts/split_outlier_bucket.py:195-234](../../scripts/split_outlier_bucket.py):

```python
def choose_k(n_docs: int, requested: int | None) -> int:
    """Pick the number of sub-clusters ``k`` for the noise bucket.
    ...
    """
    if requested:
        return max(3, min(requested, max(3, n_docs // 12)))
    return max(8, min(32, round(math.sqrt(n_docs / 2))))
```

The auto-formula `round(sqrt(n_docs / 2))` clamped to `[8, 32]` is the
arithmetic version of "scale `k` with the corpus, but stay in the band
that fits on a dashboard". For the 1,331 rows that survived the merge:
`round(sqrt(665.5)) = round(25.8) = 26`. The clamp does not bite. The
output you see in
[outputs/option2_20260502_150055/outlier_split_metrics.csv](../../outputs/option2_20260502_150055/outlier_split_metrics.csv)
confirms it:

```
metric,value
silhouette_cosine_sample,0.124
outlier_topic,-1.0
outlier_docs,1331.0
subtopics,26.0
```

Twenty-six sub-themes, real silhouette score 0.124 (we get to silhouette
in [06-cluster-quality-and-centroids.md](06-cluster-quality-and-centroids.md)).

The `/ 2` is a soft prior. In the clustering literature you also see
`sqrt(n)` (which would give 36 here) and `sqrt(n/2)` (which gives 26).
The pipeline picked the latter to bias toward coarser themes — there
is no point in cutting a 1,331-ticket noise bucket into 36 fine-grained
groups when the whole reason it is "noise" is that the underlying
structure is fuzzy.

The `requested` branch enforces "at least 12 docs per cluster on
average" so a hostile `--n-subtopics 200` does not produce 200 useless
groups of 6 docs each.

## n_init: brute-forcing past local minima

KMeans is non-convex. Different initial centroid placements can lead
to genuinely different final partitions, and many of those partitions
have terrible inertia. The standard defence is to run the whole fit
multiple times and keep the best.

From [scripts/build_user_wants_taxonomy.py:298-302](../../scripts/build_user_wants_taxonomy.py):

```python
# * ``n_init="auto"`` — sklearn picks ``n_init=10`` for the
#   standard Lloyd algorithm. Each restart picks different
#   random seeds for the initial centroids and the final
#   partition is the lowest-inertia of the bunch. This matters
#   because KMeans is non-convex and can get stuck.
```

`n_init="auto"` becomes 10 in modern sklearn. The two MiniBatchKMeans
calls bump this up: 20 inside `cluster_texts` (for the fallback), 30
inside `split_outliers` (for the production noise-split). More
restarts mean more compute for a more stable answer. Thirty is at the
"diminishing returns" point — past it, you are mostly burning CPU on
re-finding the same partition.

`random_state=42` makes the whole thing reproducible. Different seeds
would still each return the same answer (since they all keep the
lowest-inertia restart), but seeds plus order-of-iteration plus
floating-point arithmetic create enough variation that the cluster IDs
themselves can permute. Pinning the seed pins the IDs.

## The recap

- KMeans assigns every point to exactly one of `k` clusters. No noise
  bucket, no probabilities — just nearest-centroid assignment.
- The pipeline uses it in three places: as a quality fallback inside
  `cluster_wants` when HDBSCAN's output is unusable, as an availability
  fallback inside `cluster_texts` when HDBSCAN fails to import, and as
  the production algorithm inside `split_outliers` to refuse the noise
  bucket.
- `MiniBatchKMeans(n_init=30, batch_size=512)` is the production
  variant. Mini-batch is a scalability speedup; `n_init=30` is a
  brute-force defence against non-convexity.
- `k` is chosen as `sqrt(n/2)` clamped to `[8, 32]`. Each cluster ends
  up with roughly `sqrt(n*2)` members; the count of clusters and the
  size of each are roughly balanced.
- Per-row confidence is synthesised from distance ratios:
  `1 - (distance_to_assigned / mean_distance_to_all)`. KMeans does not
  give you a probability natively, so we build one out of distances.

## Try it

Reproduce the 26-sub-theme split on the 1,381 outlier tickets.

```python
import math
import numpy as np
import pandas as pd
from sklearn.cluster import MiniBatchKMeans
from sklearn.preprocessing import normalize

run = "outputs/option2_20260502_150055"
emb = np.load(f"{run}/embeddings_local.npy")
sem = pd.read_csv(f"{run}/semantic_cluster_assignments.csv")
bert = pd.read_csv(f"{run}/bertopic_assignments.csv")

merged = sem.assign(_idx=range(len(sem))).merge(
    bert[["source_row", "bertopic_topic"]], on="source_row", how="left"
)
mask = pd.to_numeric(merged["bertopic_topic"], errors="coerce").eq(-1)
outlier_idx = merged.loc[mask, "_idx"].to_numpy()
print("outlier docs:", len(outlier_idx))  # 1331

X = normalize(emb[outlier_idx])
n = len(X)
k = max(8, min(32, round(math.sqrt(n / 2))))
print(f"k = round(sqrt({n}/2)) clamped = {k}")  # 26

km = MiniBatchKMeans(n_clusters=k, random_state=42, n_init=30, batch_size=512)
labels = km.fit_predict(X)
distances = km.transform(X)
conf = 1 - (distances[np.arange(n), labels] / np.maximum(distances.mean(axis=1), 1e-9))
conf = np.clip(conf, 0, 1)

print("median confidence:", round(float(np.median(conf)), 3))
print("low-confidence (<0.2):", int((conf < 0.2).sum()))
```

The cluster sizes will be uneven by design — the largest sub-theme in
the canonical run has 112 tickets, the smallest a few dozen. Compare
your `pd.Series(labels).value_counts()` to
[outputs/option2_20260502_150055/outlier_subtopics.csv](../../outputs/option2_20260502_150055/outlier_subtopics.csv).

For the second experiment, run the same code with `n_init=1` instead
of `n_init=30` and compare the resulting sizes. You will see two or
three of the clusters shift by tens of tickets and a couple of
borderline points migrate. That instability is what `n_init=30`
suppresses.
